"""
customs_description_engine.py — Customs Description Engine for Estrella Jewels.

Supersedes polish_description_generator.py for all new code paths.
Called from dhl_clearance_handler.py and the DHL clearance API routes.

Outputs per batch:
  1. Polish-language customs description PDF  (A4, reportlab)
  2. SAD-ready JSON  (structured line-level data for customs declaration)
  3. Combined audit envelope from generate_customs_description_package()

Rules:
  - Never use vague terms in Polish output: towary, produkty, próbki, materiał, część
  - Maintain exact invoice line order in SAD JSON
  - Skip totals/freight/bank rows in SAD output
  - Approval stores name + timestamp — not just a boolean
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Service-side description engine (single source of truth) ─────────────────
# When the service path is reachable AND document_db is initialised, we read
# locked description blocks from description_engine. The engine persists the
# Polish-first / English-after-slash composed line per product_code (or per
# item_type when no real product code is supplied) and honors operator
# overrides. If unreachable, callers fall back to inline composition so the
# generator still produces a valid PDF.

def _try_load_description_engine():
    _svc = os.path.join(os.path.dirname(__file__), "service")
    if _svc not in sys.path:
        sys.path.insert(0, _svc)
    try:
        from app.services import description_engine as _eng  # type: ignore
        return _eng
    except Exception:
        return None


_DESCRIPTION_ENGINE = _try_load_description_engine()

# ── Normalization dictionaries ─────────────────────────────────────────────────

# Item type → Polish name (title case, used in running text)
ITEM_TYPE_PL: dict[str, str] = {
    "RING":      "Pierścionek",
    "EARRINGS":  "Kolczyki",
    "EARRING":   "Kolczyki",
    "BRACELET":  "Bransoletka",
    "BANGLE":    "Bransoletka sztywna",
    "PENDANT":   "Wisiorek",
    "NECKLACE":  "Naszyjnik",
    "BROOCH":    "Broszka",
    "SET":       "Komplet biżuterii",
    "CHAIN":     "Łańcuszek",
    "ANKLET":    "Bransoletka na kostkę",
    "STUD":      "Kolczyki wkrętki",
    "HOOP":      "Kolczyki kółka",
    "CUFFLINKS": "Spinki do mankietów",
    "CUFFLINK":  "Spinki do mankietów",
}

# Gold/silver purity → Polish name (nominative — used in field displays)
GOLD_PURITY: dict[str, str] = {
    # Gold
    "9KT":      "złoto próby 375",
    "09KT":     "złoto próby 375",
    "10KT":     "złoto próby 417",
    "14KT":     "złoto próby 585",
    "18KT":     "złoto próby 750",
    "22KT":     "złoto próby 916",
    "24KT":     "złoto próby 999",
    # Silver
    "925":      "srebro próby 925",
    "SL925":    "srebro próby 925",
    "SILVER":   "srebro",
    # Steel
    "SS":       "stal szlachetna",
    # Platinum — specific purities before generic fallback so PT950 wins over PLATINUM
    "PT950":    "platyna próby 950",
    "PT900":    "platyna próby 900",
    "PT850":    "platyna próby 850",
    "PLATINUM": "platyna",
}

# Genitive forms — used after preposition "z/ze" in Polish sentences
# e.g. "Pierścionek ze złota próby 585 z diamentami"
# e.g. "Pierścionek z platyny próby 950"
_PURITY_GENITIVE: dict[str, str] = {
    # Gold
    "9KT":      "złota próby 375",
    "09KT":     "złota próby 375",
    "10KT":     "złota próby 417",
    "14KT":     "złota próby 585",
    "18KT":     "złota próby 750",
    "22KT":     "złota próby 916",
    "24KT":     "złota próby 999",
    # Silver
    "925":      "srebra próby 925",
    "SL925":    "srebra próby 925",
    "SILVER":   "srebra",
    # Steel
    "SS":       "stali szlachetnej",
    # Platinum — specific purities before generic fallback
    "PT950":    "platyny próby 950",
    "PT900":    "platyny próby 900",
    "PT850":    "platyny próby 850",
    "PLATINUM": "platyny",
}

# Stone ablative forms — used after "z" (instrumental in Polish)
_STONE_INSTRUMENTAL: dict[str, str] = {
    "diamenty":                            "diamentami",
    "diamenty i kamienie szlachetne":      "diamentami i kamieniami szlachetnymi",
    "kamienie szlachetne":                 "kamieniami szlachetnymi",
    "diamenty laboratoryjne":              "diamentami laboratoryjnymi",
    "diamenty laboratoryjne laboratoryjne": "diamentami laboratoryjnymi",
    "cyrkonie":                            "cyrkoniami",
    "rubiny":                              "rubinami",
    "szmaragdy":                           "szmaragdami",
    "szafiry":                             "szafirami",
    "perły":                               "perłami",
    "moissanit":                           "moissanitem",
}

# Stone abbreviations → Polish name (None = no stones)
STONE_ABBR: dict[str, Optional[str]] = {
    "DIA":     "diamenty",
    "DIA&CLS": "diamenty i kamienie szlachetne",
    "CLS":     "kamienie szlachetne",
    "LGD":     "diamenty laboratoryjne",
    "LG":      "diamenty laboratoryjne",
    "LAB":     "diamenty laboratoryjne",
    "PLAIN":   None,
    "CZ":      "cyrkonie",
    "RUBY":    "rubiny",
    "EMERALD": "szmaragdy",
    "SAPPHIRE": "szafiry",
    "PEARL":   "perły",
    "CUBIC":   "cyrkonie",
    "MOISS":   "moissanit",
}

# Valid HS chapter ranges for jewellery (prefix → description)
HS_VALID_RANGES: dict[str, str] = {
    "7113": "Articles of jewellery and parts thereof, of precious metal",
    "7114": "Articles of goldsmiths' or silversmiths' wares",
    "7116": "Articles of natural or cultured pearls, precious/semi-precious stones",
    "7117": "Imitation jewellery",
}

# HS/CN code candidates (indicative — customs officer confirms)
HS_CANDIDATES: dict[str, str] = {
    "RING":      "7113",
    "EARRINGS":  "7113",
    "EARRING":   "7113",
    "BRACELET":  "7113",
    "BANGLE":    "7113",
    "PENDANT":   "7113",
    "NECKLACE":  "7113",
    "BROOCH":    "7117",
    "SET":       "7113",
    "CHAIN":     "7113",
    "ANKLET":    "7113",
    "STUD":      "7113",
    "HOOP":      "7113",
    "CUFFLINKS": "7113",
    "CUFFLINK":  "7113",
}

# Rows that are NOT goods — skip in SAD output
_SKIP_DESC_RE = re.compile(
    r"\b(total|subtotal|freight|insurance|bank|payment|declaration|"
    r"shipping|handling|charge|fee|tax|vat)\b",
    re.IGNORECASE,
)

# Purity pattern: 14KT, 09KT, 925, SL925, SILVER, SS
_PURITY_RE = re.compile(
    r"\b(0?9KT|10KT|14KT|18KT|22KT|24KT|SL?925|925|SILVER|SS)\b",
    re.IGNORECASE,
)

# Lab-grown detector
_LAB_RE = re.compile(r"\b(LGD|LAB[\s\-]?GROWN|LAB)\b", re.IGNORECASE)

# Item-type detector (longest first to avoid partial matches)
_ITEM_TYPE_KEYS = sorted(ITEM_TYPE_PL.keys(), key=len, reverse=True)
_ITEM_TYPE_RE   = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _ITEM_TYPE_KEYS) + r")\b",
    re.IGNORECASE,
)

# Stone detector (longest first — DIA&CLS before DIA)
_STONE_KEYS = sorted(STONE_ABBR.keys(), key=len, reverse=True)
_STONE_RE   = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _STONE_KEYS) + r")\b",
    re.IGNORECASE,
)


# ── Core normalization ─────────────────────────────────────────────────────────

def validate_hs_classification(
    item_type: str,
    material: str,
    hs_candidate: str,
    hsn_from_invoice: str = "",
) -> dict:
    """
    Validate HS classification for a jewellery item.

    Logic:
    - If hsn_from_invoice starts with 7113 and item is gold/silver jewellery → ok, 1.0
    - If hsn_from_invoice starts with 7117 but material contains gold → mismatch, 0.3
    - If hs_candidate matches hsn_from_invoice prefix → ok, 0.85
    - If no HSN from invoice → warning, 0.6 (candidate only, not confirmed)

    Returns
    -------
    dict with keys:
        classification_confidence : float  0.0–1.0
        classification_flag       : "ok" | "warning" | "mismatch"
        classification_note       : str
    """
    item_up     = (item_type or "").upper().strip()
    mat_lower   = (material  or "").lower()
    hsn_inv     = (hsn_from_invoice or "").strip()
    hs_cand     = (hs_candidate or "7113").strip()

    is_precious_metal = any(
        kw in mat_lower for kw in ("złoto", "gold", "srebro", "silver", "platinum")
    )
    is_imitation = any(
        kw in mat_lower for kw in ("imitation", "sztuczna", "sztuczne", "metal", "stal")
    ) and not is_precious_metal

    if not hsn_inv:
        # No HSN from invoice — candidate only
        return {
            "classification_confidence": 0.6,
            "classification_flag":       "warning",
            "classification_note":       (
                f"No HSN on invoice. HS candidate {hs_cand} is indicative only — "
                "not confirmed by invoice."
            ),
        }

    # Check invoice HSN against valid jewellery ranges
    inv_in_valid_range = any(hsn_inv.startswith(prefix) for prefix in HS_VALID_RANGES)

    # Mismatch: invoice says imitation (7117) but material is precious metal
    if hsn_inv.startswith("7117") and is_precious_metal:
        return {
            "classification_confidence": 0.3,
            "classification_flag":       "mismatch",
            "classification_note":       (
                f"Invoice HSN {hsn_inv} indicates imitation jewellery (7117) "
                "but material suggests precious metal — review required."
            ),
        }

    # OK: invoice HSN within valid jewellery range and matches candidate prefix
    if inv_in_valid_range and hsn_inv.startswith(hs_cand[:4]):
        desc = HS_VALID_RANGES.get(hsn_inv[:4], "jewellery")
        return {
            "classification_confidence": 1.0 if hsn_inv[:4] == hs_cand[:4] else 0.92,
            "classification_flag":       "ok",
            "classification_note":       (
                f"Invoice HSN {hsn_inv} is within valid jewellery range {hsn_inv[:4]} "
                f"({desc})."
            ),
        }

    # OK: invoice HSN matches candidate (general)
    if hsn_inv.startswith(hs_cand[:4]):
        return {
            "classification_confidence": 0.85,
            "classification_flag":       "ok",
            "classification_note":       (
                f"Invoice HSN {hsn_inv} matches HS candidate prefix {hs_cand[:4]}."
            ),
        }

    # Warning: invoice HSN in valid range but doesn't match candidate
    if inv_in_valid_range:
        return {
            "classification_confidence": 0.7,
            "classification_flag":       "warning",
            "classification_note":       (
                f"Invoice HSN {hsn_inv} is in valid jewellery range but differs "
                f"from candidate {hs_cand} — verify chapter."
            ),
        }

    # Mismatch: invoice HSN not in any valid jewellery range
    return {
        "classification_confidence": 0.2,
        "classification_flag":       "mismatch",
        "classification_note":       (
            f"Invoice HSN {hsn_inv} is outside all valid jewellery ranges "
            f"({', '.join(HS_VALID_RANGES.keys())}) — manual review required."
        ),
    }


def normalize_item_description(
    raw_description: str,
    item_type: str = "",
    hsn_from_invoice: str = "",
) -> dict:
    """
    Parse a raw invoice item description and return normalized fields.

    Parameters
    ----------
    raw_description  : str   — e.g. "14KT RING DIA&CLS"
    item_type        : str   — optional pre-resolved item type (RING, PENDANT…)
    hsn_from_invoice : str   — HSN/HS code from invoice line (e.g. "71131911")

    Returns
    -------
    dict with keys:
        item_type, item_type_pl, gold_purity_raw, gold_purity_pl,
        stones_raw, stones_pl, natural_or_lab, material_pl,
        polish_customs_description, hs_candidate, purpose_pl,
        normalized_english, classification_confidence,
        classification_flag, classification_note
    """
    raw = raw_description or ""

    # ── Detect item type ──────────────────────────────────────────────────────
    detected_type = item_type.upper().strip() if item_type else ""
    if not detected_type:
        m = _ITEM_TYPE_RE.search(raw)
        if m:
            detected_type = m.group(1).upper()
    # Normalise EARRING → EARRINGS for dict lookup; keep original for english
    lookup_type = detected_type
    if lookup_type == "EARRING":
        lookup_type = "EARRINGS"
    if lookup_type == "CUFFLINK":
        lookup_type = "CUFFLINKS"

    item_type_pl = ITEM_TYPE_PL.get(lookup_type) or ITEM_TYPE_PL.get(detected_type) or "Wyrób jubilerski"
    hs_candidate = HS_CANDIDATES.get(lookup_type) or HS_CANDIDATES.get(detected_type) or "7113"

    # ── Detect purity / material ──────────────────────────────────────────────
    purity_raw  = ""
    purity_pl   = ""
    raw_upper = raw.upper()
    for key, val in GOLD_PURITY.items():
        pattern = re.compile(r"\b" + re.escape(key) + r"\b", re.IGNORECASE)
        if pattern.search(raw):
            purity_raw = key
            purity_pl  = val
            break

    # ── Detect stones ─────────────────────────────────────────────────────────
    stones_raw = ""
    stones_pl  = ""
    # Check compound first (DIA&CLS must beat DIA)
    for key in _STONE_KEYS:
        pattern = re.compile(r"\b" + re.escape(key) + r"\b", re.IGNORECASE)
        if pattern.search(raw):
            stones_raw = key.upper()
            stones_pl  = STONE_ABBR.get(key.upper()) or STONE_ABBR.get(key) or ""
            break

    # ── Fallback: detect full English stone words when no abbreviation matched ─
    if not stones_pl:
        raw_up = raw.upper()
        # "Diamond & Colour Stone" or "Diamond and Colour Stone"
        if re.search(r"\bDIAMOND\b", raw_up) and re.search(r"\b(COLOUR|COLOR)\s+STONE\b", raw_up):
            stones_raw = "DIA&CLS"
            stones_pl  = "diamenty i kamienie szlachetne"
        elif re.search(r"\bDIAMOND\b", raw_up):
            stones_raw = "DIA"
            stones_pl  = "diamenty"
        elif re.search(r"\b(COLOUR|COLOR)\s+STONE\b", raw_up) or re.search(r"\bGEMSTONE\b", raw_up):
            stones_raw = "CLS"
            stones_pl  = "kamienie szlachetne"
        elif re.search(r"\bRUBY\b", raw_up):
            stones_raw = "RUBY"; stones_pl = "rubiny"
        elif re.search(r"\bSAPPHIRE\b", raw_up):
            stones_raw = "SAPPHIRE"; stones_pl = "szafiry"
        elif re.search(r"\bEMERALD\b", raw_up):
            stones_raw = "EMERALD"; stones_pl = "szmaragdy"
        elif re.search(r"\bPEARL\b", raw_up):
            stones_raw = "PEARL"; stones_pl = "perły"
        elif re.search(r"\bMOISSANIT\b", raw_up):
            stones_raw = "MOISS"; stones_pl = "moissanit"

    # ── Natural vs lab-grown ──────────────────────────────────────────────────
    natural_or_lab = "natural"
    if _LAB_RE.search(raw) or stones_raw in ("LGD", "LG", "LAB"):
        natural_or_lab = "lab_grown"
        if stones_pl and "laboratoryjne" not in stones_pl:
            stones_pl = stones_pl.rstrip() + " laboratoryjne"

    # ── Resolve genitive / instrumental forms for Polish grammar ─────────────
    purity_gen    = _PURITY_GENITIVE.get(purity_raw, purity_pl)   # "złota próby 585"
    stones_instr  = _STONE_INSTRUMENTAL.get(stones_pl.strip(), stones_pl)  # "diamentami"

    # Preposition: "ze" before words starting with z/ż/ź/zł, "z" otherwise
    def _prep(word: str) -> str:
        return "ze" if word and word[0].lower() in ("z", "ż", "ź") else "z"

    # ── Compose material_pl (nominative — for field display) ─────────────────
    if purity_pl and stones_pl:
        material_pl = f"{purity_pl} z {stones_pl}"
    elif purity_pl:
        material_pl = purity_pl
    elif stones_pl:
        material_pl = f"metal z {stones_pl}"
    else:
        material_pl = "metal szlachetny"

    # ── Compose polish_customs_description (correct Polish grammar) ───────────
    if purity_gen and stones_instr:
        prep = _prep(purity_gen)
        item_desc = (
            f"{item_type_pl} {prep} {purity_gen} "
            f"z {stones_instr}, biżuteria do noszenia."
        )
    elif purity_gen:
        prep = _prep(purity_gen)
        item_desc = f"{item_type_pl} {prep} {purity_gen}, biżuteria do noszenia."
    elif stones_instr:
        item_desc = f"{item_type_pl} z {stones_instr}, biżuteria do noszenia."
    else:
        item_desc = f"{item_type_pl} — wyrób jubilerski do noszenia."

    # ── purpose_pl ────────────────────────────────────────────────────────────
    purpose_pl = "Ozdoba — biżuteria do noszenia."

    # ── Normalized English ────────────────────────────────────────────────────
    en_parts = []
    if purity_raw:
        en_parts.append(purity_raw.replace("KT", " karat").replace("kt", " karat").lower() + " gold")
    if detected_type:
        en_parts.append(detected_type.lower() + ("s" if detected_type in ("RING", "PENDANT") else ""))
    if stones_pl:
        stone_en_map = {
            "diamenty":                            "diamonds",
            "diamenty i kamienie szlachetne":      "diamonds and gemstones",
            "kamienie szlachetne":                 "gemstones",
            "diamenty laboratoryjne":              "lab-grown diamonds",
            "diamenty laboratoryjne laboratoryjne": "lab-grown diamonds",
            "cyrkonie":                            "cubic zirconia",
            "rubiny":                              "rubies",
            "szmaragdy":                           "emeralds",
            "szafiry":                             "sapphires",
            "perły":                               "pearls",
            "moissanit":                           "moissanite",
        }
        en_stones = stone_en_map.get(stones_pl.strip(), stones_pl)
        en_parts.append("with " + en_stones)
    normalized_english = " ".join(en_parts) if en_parts else raw

    # ── HS classification validation ──────────────────────────────────────────
    hs_validation = validate_hs_classification(
        item_type        = detected_type or lookup_type,
        material         = material_pl,
        hs_candidate     = hs_candidate,
        hsn_from_invoice = hsn_from_invoice,
    )

    return {
        "item_type":                   detected_type or lookup_type,
        "item_type_pl":                item_type_pl,
        "gold_purity_raw":             purity_raw,
        "gold_purity_pl":              purity_pl,
        "stones_raw":                  stones_raw,
        "stones_pl":                   stones_pl,
        "natural_or_lab":              natural_or_lab,
        "material_pl":                 material_pl,
        "polish_customs_description":  item_desc,
        "hs_candidate":                hs_candidate,
        "purpose_pl":                  purpose_pl,
        "normalized_english":          normalized_english,
        "classification_confidence":   hs_validation["classification_confidence"],
        "classification_flag":         hs_validation["classification_flag"],
        "classification_note":         hs_validation["classification_note"],
        "hsn_from_invoice":            hsn_from_invoice,
    }


# ── Batch-level processing ─────────────────────────────────────────────────────

def process_batch_items(batch: dict) -> list[dict]:
    """
    Flatten all invoice line items from a batch, normalize each one,
    and return a list of SAD-ready line dicts in invoice order.

    Skips total/freight/bank rows.

    Parameters
    ----------
    batch : dict — batch audit dict (from audit.json or process_batch result)

    Returns
    -------
    list of SAD-ready line dicts
    """
    invoices = _extract_invoices(batch)
    lines: list[dict] = []
    order = 0

    for inv in invoices:
        inv_number = inv.get("invoice_number") or inv.get("invoice_no") or inv.get("number") or ""
        for item in inv.get("items", []):
            desc = (
                item.get("description") or
                item.get("desc") or
                item.get("name") or
                ""
            )

            # Skip non-goods rows
            item_type_raw = (
                item.get("item_type") or
                item.get("type") or
                ""
            ).upper().strip()
            if not item_type_raw and _SKIP_DESC_RE.search(desc):
                continue
            if not desc and not item_type_raw:
                continue

            order += 1
            hsn_code = (
                item.get("hsn_code") or
                item.get("hs_code") or
                item.get("hsn") or
                ""
            )
            norm = normalize_item_description(
                desc,
                item_type=item_type_raw,
                hsn_from_invoice=str(hsn_code) if hsn_code else "",
            )

            qty = item.get("quantity") or item.get("qty") or item.get("line_qty") or 0
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                qty = 0.0

            unit_price = item.get("unit_price") or item.get("rate") or item.get("price") or 0.0
            try:
                unit_price = float(str(unit_price).replace(",", ""))
            except (TypeError, ValueError):
                unit_price = 0.0

            line_total = item.get("line_total") or item.get("amount") or item.get("total") or 0.0
            try:
                line_total = float(str(line_total).replace(",", ""))
            except (TypeError, ValueError):
                # Compute from qty × unit_price if not present
                line_total = qty * unit_price

            lines.append({
                "line_order":                     order,
                "invoice_number":                 str(inv_number),
                "product_code":                   str(item.get("product_code") or ""),
                "original_description":           desc,
                "normalized_english_description": norm["normalized_english"],
                "polish_customs_description":     norm["polish_customs_description"],
                "item_type":                      norm["item_type"],
                "item_type_pl":                   norm["item_type_pl"],
                "material":                       norm["material_pl"],
                "gold_purity":                    norm["gold_purity_raw"],
                "stones":                         norm["stones_pl"],
                "natural_or_lab_grown":           norm["natural_or_lab"],
                "purpose":                        norm["purpose_pl"],
                "hs_candidate":                   norm["hs_candidate"],
                "hsn_from_invoice":               norm["hsn_from_invoice"],
                "classification_confidence":      norm["classification_confidence"],
                "classification_flag":            norm["classification_flag"],
                "classification_note":            norm["classification_note"],
                "quantity":                       qty,
                "uom":                            (item.get("unit") or item.get("uom") or "PCS").upper(),
                "gross_weight_g":                 _safe_float(item.get("gross_weight") or item.get("gross")),
                "net_weight_g":                   _safe_float(item.get("net_weight") or item.get("net")),
                "value_usd":                      unit_price,
                "line_total_usd":                 line_total,
            })

    return lines


# ── SAD-ready JSON generator ───────────────────────────────────────────────────

def generate_sad_ready_json(
    batch: dict,
    awb: str,
    output_dir: str,
    dhl_email_id: str = "",
) -> dict:
    """
    Generate a SAD-ready JSON file for the batch.

    Parameters
    ----------
    batch        : batch audit dict
    awb          : AWB number
    output_dir   : directory to write the file
    dhl_email_id : optional DHL email ID for audit trail

    Returns
    -------
    dict with: generated, output_path, filename, total_lines, json_hash
    """
    try:
        return _generate_sad_json(batch, awb, output_dir, dhl_email_id)
    except Exception as exc:
        return {
            "generated":   False,
            "output_path": None,
            "filename":    None,
            "total_lines": 0,
            "json_hash":   None,
            "error":       str(exc),
        }


def _generate_sad_json(
    batch: dict,
    awb: str,
    output_dir: str,
    dhl_email_id: str,
) -> dict:
    awb_clean  = re.sub(r"\s+", "", awb)
    today      = datetime.now(timezone.utc).strftime("%d-%m-%Y")
    filename   = f"SAD_READY_{awb_clean}_{today}.json"
    out_dir    = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / filename)

    lines    = process_batch_items(batch)
    invoices = _extract_invoices(batch)

    # Count unique invoice numbers
    inv_numbers = set(line["invoice_number"] for line in lines if line["invoice_number"])

    # SAD_READY top-level total_value_usd is the customs value (CIF), not the
    # FOB sum of line totals. This aligns the JSON output with:
    #   • the PDF generator's `grand_total_usd = cif_usd` (see line ~1239)
    #   • clearance_decision.total_value_usd everywhere else in the codebase
    #   • CLAUDE.md customs-value rules (CIF = FOB + freight + insurance)
    #
    # Resolution order — first non-zero source wins. Mirrors the PDF
    # generator's cif_usd fallback chain to keep JSON and PDF in lock-step:
    #   1. invoice_totals.total_cif_usd                  (canonical)
    #   2. sum of per-invoice inv["cif_usd"]             (parsed invoices)
    #   3. verification.invoice_cif_total_usd            (verifier output)
    #   4. customs_declaration.invoice_cif_usd           (legacy audit shape)
    #   5. sum of line_total_usd (FOB fallback)          (legacy batches)
    #   6. 0.0                                            (no data)
    invoice_totals_for_total = batch.get("invoice_totals") or {}
    verification_for_total   = (
        (batch.get("result") or {}).get("verification")
        or batch.get("verification")
        or {}
    )
    customs_decl_for_total   = batch.get("customs_declaration") or {}
    total_value = (
        _safe_float(invoice_totals_for_total.get("total_cif_usd"))
        or sum(
            _safe_float(inv.get("cif_usd") or 0) or 0.0 for inv in invoices
        )
        or _safe_float(verification_for_total.get("invoice_cif_total_usd"))
        or _safe_float(customs_decl_for_total.get("invoice_cif_usd"))
        or sum(line["line_total_usd"] for line in lines)
        or 0.0
    )

    # Source invoice hash — sha256 of the audit.json content if available
    source_hash = _compute_source_hash(batch)

    batch_id = (
        batch.get("batch_id") or
        (batch.get("batch_meta") or {}).get("batch_id") or
        ""
    )

    # ── Classification summary ────────────────────────────────────────────────
    hs_ok          = [l for l in lines if l.get("classification_flag") == "ok"]
    hs_warnings    = [l for l in lines if l.get("classification_flag") == "warning"]
    hs_mismatches  = [l for l in lines if l.get("classification_flag") == "mismatch"]
    lines_with_hsn = [l for l in lines if l.get("hsn_from_invoice")]
    lines_no_hsn   = [l for l in lines if not l.get("hsn_from_invoice")]

    classification_summary = {
        "all_ok":                  len(hs_warnings) == 0 and len(hs_mismatches) == 0,
        "warnings":                len(hs_warnings),
        "mismatches":              len(hs_mismatches),
        "lines_with_hs_from_invoice": len(lines_with_hsn),
        "lines_without_hs":        len(lines_no_hsn),
    }

    # ── Customs value breakdown ───────────────────────────────────────────────
    verification = (batch.get("result") or {}).get("verification") or {}
    fob       = sum(_safe_float(inv.get("fob_usd") or 0) or 0.0 for inv in invoices)
    freight   = sum(_safe_float(inv.get("freight_usd") or 0) or 0.0 for inv in invoices)
    insurance = sum(_safe_float(inv.get("insurance_usd") or 0) or 0.0 for inv in invoices)
    cif       = sum(_safe_float(inv.get("cif_usd") or 0) or 0.0 for inv in invoices)
    if cif == 0.0:
        cif = _safe_float(verification.get("invoice_cif_total_usd")) or 0.0

    customs_value_breakdown = {
        "fob_usd":       round(fob, 2),
        "freight_usd":   round(freight, 2),
        "insurance_usd": round(insurance, 2),
        "cif_usd":       round(cif, 2),
        "source":        "invoice_parsed" if fob > 0 else "verification_block",
    }

    # ── Error flags ───────────────────────────────────────────────────────────
    hs_mismatch_lines   = [l["line_order"] for l in hs_mismatches]
    unclear_desc_lines  = [
        l["line_order"] for l in lines
        if (l.get("classification_confidence") or 1.0) < 0.5
    ]
    error_flags = {
        "missing_awb":         not awb_clean,
        "hs_mismatch_lines":   hs_mismatch_lines,
        "unclear_descriptions": unclear_desc_lines,
        "unmatched_email":     not dhl_email_id,
        "fob_missing":         fob == 0.0 and cif == 0.0,
        "any_errors":          bool(
            not awb_clean or hs_mismatch_lines or unclear_desc_lines or (fob == 0.0 and cif == 0.0)
        ),
    }

    payload = {
        "awb":                      awb_clean,
        "batch_id":                 batch_id,
        "generated_at":             datetime.now(timezone.utc).isoformat(),
        "dhl_email_id":             dhl_email_id,
        "invoice_count":            len(invoices),
        "total_lines":              len(lines),
        "total_value_usd":          round(total_value, 2),
        "declaration_type":         "dopuszczenie do obrotu",
        "declaration_type_override": False,
        "declaration_type_options": [
            "dopuszczenie do obrotu",
            "tranzyt",
            "procedura składowania",
            "uszlachetnianie czynne",
        ],
        "customs_value_breakdown":  customs_value_breakdown,
        "classification_summary":   classification_summary,
        "error_flags":              error_flags,
        "lines":                    lines,
        "source_invoice_hash":      source_hash,
        "json_hash":                "",          # computed below
        "audit": {
            "approved_by":  None,
            "approved_at":  None,
        },
    }

    # Compute hash over lines + core fields (exclude json_hash itself)
    hash_content = json.dumps(
        {k: v for k, v in payload.items() if k != "json_hash"},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    json_hash = hashlib.sha256(hash_content).hexdigest()
    payload["json_hash"] = json_hash

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return {
        "generated":   True,
        "output_path": output_path,
        "filename":    filename,
        "total_lines": len(lines),
        "json_hash":   json_hash,
        "error":       None,
    }


# ── Polish description PDF generator ──────────────────────────────────────────

_CONSIGNOR_UNRESOLVED_SENTINEL = "[DOSTAWCA NIEOKREŚLONY / SUPPLIER UNRESOLVED]"
_CONSIGNEE_FALLBACK            = "ESTRELLA JEWELS SP. Z O.O. SP.K."


def generate_polish_description_pdf(
    batch: dict,
    awb: str,
    output_dir: str,
    dhl_email_id: str = "",
    date_override: Optional[str] = None,
    *,
    consignee_name: Optional[str] = None,
    consignor_name: Optional[str] = None,
) -> dict:
    """
    Generate a Polish-language A4 customs description PDF.

    Supersedes polish_description_generator.generate_polish_description().
    Call this from dhl_clearance_handler.py going forward.

    Parameters
    ----------
    batch         : batch audit dict
    awb           : AWB number
    output_dir    : directory to write the file
    dhl_email_id  : optional DHL email ID (shown in header)
    date_override : YYYY-MM-DD (defaults to today UTC)
    consignee_name: when provided (non-None), overrides the hardcoded consignee
                    constant.  Empty string → use the hardcoded fallback.
    consignor_name: when provided (non-None), overrides the batch-parsed exporter
                    name.  Empty string → current batch-parse logic applies.
                    Pass _CONSIGNOR_UNRESOLVED_SENTINEL to surface an explicit
                    "supplier not resolved" notice on the PDF rather than
                    silently printing the wrong company name.

    Returns
    -------
    dict with: generated, output_path, filename, items_described, pdf_hash
    """
    try:
        return _generate_pdf(
            batch, awb, output_dir, dhl_email_id, date_override,
            consignee_name=consignee_name,
            consignor_name=consignor_name,
        )
    except Exception as exc:
        return {
            "generated":       False,
            "output_path":     None,
            "filename":        None,
            "items_described": 0,
            "pdf_hash":        None,
            "error":           str(exc),
        }


def _register_unicode_font() -> tuple[str, str]:
    """
    Register a Unicode TTF font with ReportLab so Polish characters render correctly.

    Tries (in order):
    1. Arial Unicode (macOS system font — full Unicode coverage)
    2. DejaVuSans (common Linux/Python package font)
    3. FreeSans (Linux)
    4. Falls back to Helvetica (ASCII only — Polish chars will be replaced by boxes)

    Returns (normal_font_name, bold_font_name) registered with pdfmetrics.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Candidate font paths: (normal_path, bold_path_or_None, registered_name)
    candidates = [
        # macOS system fonts
        ("/Library/Fonts/Arial Unicode.ttf",                                None,                                                   "ArialUnicode"),
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",            None,                                                   "ArialUnicode"),
        # DejaVu (often installed alongside reportlab, or via system package)
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  "DejaVuSans"),
        ("/usr/share/fonts/dejavu/DejaVuSans.ttf",                          "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",           "DejaVuSans"),
        # FreeSans (Linux)
        ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",                 "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",   "FreeSans"),
        # Windows system fonts
        (r"C:\Windows\Fonts\DejaVuSans.ttf",                                r"C:\Windows\Fonts\DejaVuSans-Bold.ttf",                "DejaVuSans"),
        (r"C:\Windows\Fonts\arial.ttf",                                     r"C:\Windows\Fonts\arialbd.ttf",                        "Arial"),
    ]

    # Also look next to this file and in the engine dir
    here = Path(__file__).parent
    local_candidates = [
        (str(here / "fonts" / "DejaVuSans.ttf"), str(here / "fonts" / "DejaVuSans-Bold.ttf"), "DejaVuSans"),
        (str(here / "DejaVuSans.ttf"),           str(here / "DejaVuSans-Bold.ttf"),            "DejaVuSans"),
    ]
    candidates = local_candidates + candidates

    for norm_path, bold_path, name in candidates:
        if not Path(norm_path).is_file():
            continue
        try:
            # Register normal
            pdfmetrics.registerFont(TTFont(name, norm_path))
            # Register bold — use same file if no separate bold (Arial Unicode has no separate bold TTF)
            bold_name = name + "-Bold"
            if bold_path and Path(bold_path).is_file():
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            else:
                pdfmetrics.registerFont(TTFont(bold_name, norm_path))
            return name, bold_name
        except Exception:
            continue

    # No Unicode font found — hard fail to prevent broken PDFs with black squares
    raise RuntimeError(
        "Unicode font required for Polish PDF not found. "
        "Install Arial Unicode or DejaVuSans, or bundle fonts/DejaVuSans.ttf next to the engine."
    )


def _generate_pdf(
    batch: dict,
    awb: str,
    output_dir: str,
    dhl_email_id: str,
    date_override: Optional[str],
    *,
    consignee_name: Optional[str] = None,
    consignor_name: Optional[str] = None,
) -> dict:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
        KeepTogether, Image,
    )

    awb_clean = re.sub(r"\s+", "", awb)
    today     = date_override or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_disp = _fmt_date_pl(today)
    date_fn   = today.replace("-", "")
    gen_ts    = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    filename    = f"POLISH_DESC_AWB_{awb_clean}_{date_fn}.pdf"
    out_dir     = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / filename)

    # Delete stale PDFs for the same AWB so the browser never serves an old broken file
    for stale in out_dir.glob(f"POLISH_DESC*{awb_clean}*.pdf"):
        if str(stale) != output_path:
            try:
                stale.unlink()
            except OSError:
                pass

    # ── Register Unicode font ─────────────────────────────────────────────────
    FONT, FONT_BOLD = _register_unicode_font()

    # ── Extract data ──────────────────────────────────────────────────────────
    lines    = process_batch_items(batch)
    invoices = _extract_invoices(batch)

    # ── Consignor (Nadawca / Shipper) ─────────────────────────────────────────
    # Priority: caller-supplied override → batch-parsed → hardcoded fallback.
    # None means "no override provided" (flag_off); caller uses current behavior.
    # Non-None means "flag_on": use the supplied value (which may be a resolved
    # supplier name, an empty string meaning "use batch parse", or the
    # _CONSIGNOR_UNRESOLVED_SENTINEL meaning "supplier not resolved — flag it").
    if consignor_name is not None:
        # flag_on path: use exactly what the caller resolved
        exporter = consignor_name if consignor_name else _get_exporter(batch)
    else:
        # flag_off path: current behavior
        exporter = _get_exporter(batch)

    # ── Consignee (Odbiorca / Consignee) ─────────────────────────────────────
    # None means "no override" (flag_off) → current constant.
    # Non-None and non-empty → use the supplied value (from company_profile).
    # Non-None but empty → fall back to the hardcoded constant (company_profile
    # row exists but legal_name is blank).
    if consignee_name is not None and consignee_name.strip():
        _consignee = consignee_name.strip()
    else:
        _consignee = _CONSIGNEE_FALLBACK

    if not lines:
        lines = _build_synthetic_lines_from_totals(batch)

    invoice_totals = batch.get("invoice_totals") or {}
    cif_usd = (
        _safe_float(invoice_totals.get("total_cif_usd")) or
        sum(line["line_total_usd"] for line in lines) or
        _safe_float((batch.get("verification") or {}).get("invoice_cif_total_usd")) or
        _safe_float((batch.get("customs_declaration") or {}).get("invoice_cif_usd")) or
        0.0
    )

    inv_refs = (batch.get("inputs") or {}).get("invoice_refs") or []
    if not inv_refs:
        inv_refs = _extract_invoice_refs_from_names(batch)
    if not inv_refs:
        seen: set = set()
        for ln in lines:
            if ln["invoice_number"] and ln["invoice_number"] not in seen:
                inv_refs.append(ln["invoice_number"])
                seen.add(ln["invoice_number"])

    dhl_ticket = (
        batch.get("dhl_ticket") or
        (batch.get("dhl_email") or {}).get("dhl_ticket") or
        dhl_email_id or
        ""
    )

    # ── B&W colour palette ────────────────────────────────────────────────────
    BLACK      = colors.black
    DARK_GRAY  = colors.HexColor("#222222")
    MID_GRAY   = colors.HexColor("#666666")
    LIGHT_GRAY = colors.HexColor("#F5F5F5")
    RULE_GRAY  = colors.HexColor("#BBBBBB")

    # ── Styles ────────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    def _ps(name, fn=None, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], fontName=(fn or FONT), **kw)

    CO_NAME    = _ps("PLCoName",  fn=FONT_BOLD, fontSize=11, leading=14, textColor=DARK_GRAY)
    TITLE      = _ps("PLTitle",   fn=FONT_BOLD, fontSize=12, leading=16, spaceAfter=2,  textColor=DARK_GRAY)
    SUBTTL     = _ps("PLSubTtl",  fn=FONT,      fontSize=8,  leading=11, spaceAfter=4,  textColor=MID_GRAY)
    HDR_LBL    = _ps("PLHdrL",    fn=FONT_BOLD, fontSize=7.5, leading=10, textColor=MID_GRAY)
    HDR_VAL    = _ps("PLHdrV",    fn=FONT,      fontSize=7.5, leading=10, textColor=DARK_GRAY)
    INV_HDR    = _ps("PLInvHdr",  fn=FONT_BOLD, fontSize=9,  leading=12, textColor=DARK_GRAY,
                     spaceBefore=5, spaceAfter=2)
    ITEM_NUM   = _ps("PLItemNum", fn=FONT_BOLD, fontSize=8,  leading=11, textColor=DARK_GRAY,
                     spaceBefore=4, spaceAfter=1)
    FIELD_LBL  = _ps("PLFldLbl",  fn=FONT_BOLD, fontSize=7.5, leading=10, textColor=MID_GRAY)
    FIELD_VAL  = _ps("PLFldVal",  fn=FONT,      fontSize=7.5, leading=10, textColor=DARK_GRAY,
                     wordWrap="CJK")
    SUBTOT_S   = _ps("PLSubTot",  fn=FONT_BOLD, fontSize=7.5, leading=10, textColor=DARK_GRAY)
    GRAND_S    = _ps("PLGrand",   fn=FONT_BOLD, fontSize=8.5, leading=11, textColor=DARK_GRAY)
    SIG_LBL    = _ps("PLSig",     fn=FONT,      fontSize=8,   leading=11, textColor=DARK_GRAY)
    FOOTER     = _ps("PLFtr",     fn=FONT,      fontSize=6.5, leading=9,  textColor=MID_GRAY,
                     alignment=1)

    # ── Page layout ───────────────────────────────────────────────────────────
    PAGE_W, PAGE_H = A4
    L_MARGIN = R_MARGIN = 18 * mm
    CONTENT_W = PAGE_W - L_MARGIN - R_MARGIN

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=16 * mm, bottomMargin=20 * mm,
        title=f"Opis Towarów — AWB {awb_clean}",
        author="Estrella Jewels Sp. z o.o. Sp. k.",
        subject="Opis towarów do odprawy celnej DHL",
    )

    story: list = []

    # ── Header: logo (if present) + company name ──────────────────────────────
    logo_candidates = [
        Path(__file__).parent / "storage" / "assets" / "logo.png",
        Path(__file__).parent.parent / "storage" / "assets" / "logo.png",
        Path(__file__).parent / "assets" / "logo.png",
    ]
    logo_path = next((p for p in logo_candidates if p.exists()), None)

    co_para = Paragraph("ESTRELLA JEWELS Sp. z o.o. Sp. k.", CO_NAME)
    if logo_path:
        try:
            logo_img = Image(str(logo_path), width=38 * mm, height=14 * mm, kind="proportional")
            hdr_row = [[logo_img, co_para]]
            hdr_tbl = Table(hdr_row, colWidths=[42 * mm, CONTENT_W - 42 * mm])
            hdr_tbl.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN",         (1, 0), (1, 0),   "RIGHT"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(hdr_tbl)
        except Exception:
            story.append(co_para)
    else:
        story.append(co_para)

    story.append(HRFlowable(width="100%", thickness=1.5, color=BLACK, spaceBefore=3, spaceAfter=5))

    # ── Document title ────────────────────────────────────────────────────────
    story.append(Paragraph("OPIS TOWARÓW DO ODPRAWY CELNEJ DHL", TITLE))
    story.append(Paragraph("Goods Description for DHL Customs Clearance", SUBTTL))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_GRAY, spaceAfter=5))

    # ── Header info grid (bilingual labels) ───────────────────────────────────
    inv_refs_str = ", ".join(str(r) for r in inv_refs) if inv_refs else "—"
    inv_count    = (
        len(inv_refs) if inv_refs
        else (len(invoices) if invoices
              else len(set(ln["invoice_number"] for ln in lines if ln["invoice_number"])))
    )

    hdr_data = [
        [Paragraph("AWB / Nr listu:",         HDR_LBL), Paragraph(awb_clean, HDR_VAL),
         Paragraph("Data / Date:",             HDR_LBL), Paragraph(date_disp, HDR_VAL)],
        [Paragraph("Nadawca / Shipper:",       HDR_LBL),
         Paragraph(exporter or "Estrella Jewels LLP.", HDR_VAL),
         Paragraph("Odbiorca / Consignee:",    HDR_LBL),
         Paragraph(_consignee, HDR_VAL)],
        [Paragraph("Faktury / Invoices:",      HDR_LBL),
         Paragraph(f"{inv_count} szt. ({inv_refs_str})", HDR_VAL),
         Paragraph("Wartość CIF / CIF Value:", HDR_LBL),
         Paragraph("USD {:,.2f}".format(cif_usd), HDR_VAL)],
    ]
    if dhl_ticket:
        hdr_data.append([
            Paragraph("Zgłoszenie DHL / Ticket:", HDR_LBL), Paragraph(dhl_ticket, HDR_VAL),
            Paragraph("", HDR_LBL), Paragraph("", HDR_VAL),
        ])

    col_w = CONTENT_W / 4
    hdr_tbl = Table(hdr_data, colWidths=[col_w * 0.55, col_w * 1.45, col_w * 0.55, col_w * 1.45])
    hdr_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("BOX",           (0, 0), (-1, -1), 0.5, RULE_GRAY),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, RULE_GRAY),
    ]))
    story.append(hdr_tbl)
    story.append(Spacer(1, 5 * mm))

    # ── Per-invoice item blocks ───────────────────────────────────────────────
    # Group lines by invoice_number preserving original order
    inv_groups: dict[str, list] = {}
    inv_order: list[str] = []
    # Preserve the inv_refs ordering when present (so groups appear in
    # invoice-number order rather than first-line order).
    _ref_index = {str(r): i for i, r in enumerate(inv_refs)} if inv_refs else {}
    for ln in lines:
        inv_no = ln["invoice_number"] or "—"
        if inv_no not in inv_groups:
            inv_groups[inv_no] = []
            inv_order.append(inv_no)
        inv_groups[inv_no].append(ln)
    if _ref_index:
        inv_order.sort(key=lambda x: _ref_index.get(x, 10**9))

    LABEL_W = 42 * mm
    VALUE_W = CONTENT_W - LABEL_W

    for inv_idx, inv_no in enumerate(inv_order, 1):
        inv_lines = inv_groups[inv_no]

        # Invoice section header
        inv_hdr_tbl = Table(
            [[Paragraph(f"FAKTURA / INVOICE {inv_idx}:  {inv_no}", INV_HDR)]],
            colWidths=[CONTENT_W],
        )
        inv_hdr_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GRAY),
            ("BOX",           (0, 0), (-1, -1), 0.8, BLACK),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(inv_hdr_tbl)

        # Per-item bilingual field blocks
        for item_idx, ln in enumerate(inv_lines, 1):
            qty_disp = (
                "{:.0f}".format(ln["quantity"])
                if ln["quantity"] == int(ln["quantity"])
                else "{}".format(ln["quantity"])
            )
            val_disp = "USD {:,.2f}".format(ln["line_total_usd"])
            uom      = ln.get("uom") or "PCS"
            material = ln.get("material") or "—"
            purpose  = ln.get("purpose") or "Ozdoba — biżuteria do noszenia."

            item_block: list = []
            item_block.append(Paragraph(
                f"Pozycja {item_idx} / Item {item_idx}:", ITEM_NUM
            ))

            # ── Description content: Polish first / English after slash ────
            # Pull the locked composed line from description_engine when it
            # is reachable AND document_db has been initialised. Engine key
            # prefers the real product_code; falls back to item_type so the
            # type-default still resolves when product_code is not present
            # on the upstream item dict. If the engine returns nothing, use
            # inline composition with the same separator / order.
            polish = ln.get("polish_customs_description", "")
            english = ln.get("original_description", "")
            description_line = None
            if _DESCRIPTION_ENGINE is not None:
                try:
                    block = _DESCRIPTION_ENGINE.get_description_block(
                        product_code   = ln.get("product_code") or ln.get("item_type", ""),
                        item_type      = ln.get("item_type", ""),
                        description_en = english,
                        # Pass the customs engine's richer per-line Polish
                        # so the engine's first-write captures the rich
                        # phrasing (e.g. "Pierścionek z diamentami i
                        # kamieniami szlachetnymi") rather than the
                        # ITEM_TRANSLATIONS type-default.
                        description_pl = polish,
                        material_pl    = ln.get("material") or "",
                        purpose_pl     = ln.get("purpose")  or "",
                        name_pl        = ln.get("item_type_pl") or "",
                    )
                    description_line = (block or {}).get("description_line")
                except Exception:
                    description_line = None
            if not description_line:
                if polish and english:
                    description_line = f"{polish} / {english}"
                else:
                    description_line = polish or english

            fields = [
                ("Co to za towar / What is this:",     description_line),
                ("Z jakiego materiału / Material:",    material),
                ("Do czego służy / Purpose:",          purpose),
                ("Ilość / Quantity:",                  "{} {}".format(qty_disp, uom)),
                ("Wartość / Value:",                   val_disp),
            ]

            field_data = [
                [Paragraph(lbl, FIELD_LBL), Paragraph(str(val), FIELD_VAL)]
                for lbl, val in fields
            ]
            field_tbl = Table(field_data, colWidths=[LABEL_W, VALUE_W])
            field_tbl.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING",   (0, 0), (-1, -1), 4),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
                ("GRID",          (0, 0), (-1, -1), 0.3, RULE_GRAY),
                ("BACKGROUND",    (0, 0), (0, -1),  LIGHT_GRAY),
            ]))
            item_block.append(field_tbl)
            story.append(KeepTogether(item_block))

        # Per-invoice subtotal
        inv_total_usd = sum(ln["line_total_usd"] for ln in inv_lines)
        inv_total_qty = sum(ln["quantity"]        for ln in inv_lines)
        subtot_tbl = Table(
            [[
                Paragraph(
                    "Razem faktura / Invoice total: {} pozycji / items".format(len(inv_lines)),
                    SUBTOT_S,
                ),
                Paragraph(
                    "{:.0f} PCS  |  USD {:,.2f}".format(inv_total_qty, inv_total_usd),
                    SUBTOT_S,
                ),
            ]],
            colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4],
        )
        subtot_tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("BOX",           (0, 0), (-1, -1), 0.5, BLACK),
            ("ALIGN",         (1, 0), (1, 0),   "RIGHT"),
        ]))
        story.append(subtot_tbl)
        story.append(Spacer(1, 4 * mm))

    # ── Consolidated customs summary (per item type, across all invoices) ────
    type_groups = _consolidate_by_type(lines)
    if type_groups:
        story.append(Spacer(1, 4 * mm))
        story.append(HRFlowable(width="100%", thickness=0.6, color=BLACK, spaceAfter=2))
        story.append(Paragraph(
            "PODSUMOWANIE / CONSOLIDATED CUSTOMS SUMMARY", INV_HDR,
        ))

        sum_header = [
            Paragraph("Typ / Type",        SUBTOT_S),
            Paragraph("Ilość / Qty",       SUBTOT_S),
            Paragraph("Wartość / Value",   SUBTOT_S),
        ]
        sum_rows = [sum_header]
        # uom per type from the synthetic line (first line of each type)
        type_uom: dict[str, str] = {}
        for ln in lines:
            t = ln.get("item_type") or ""
            if t and t not in type_uom:
                type_uom[t] = ln.get("uom") or "PCS"
        for grp in type_groups:
            t = grp["item_type"]
            uom = type_uom.get(t, "PCS")
            qty = grp["total_qty"]
            qty_disp = "{:.0f}".format(qty) if qty == int(qty) else "{}".format(qty)
            sum_rows.append([
                Paragraph(t,                                       FIELD_VAL),
                Paragraph(f"{qty_disp} {uom}",                     FIELD_VAL),
                Paragraph("USD {:,.2f}".format(grp["total_value_usd"]), FIELD_VAL),
            ])
        sum_tbl = Table(
            sum_rows,
            colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.25, CONTENT_W * 0.30],
        )
        sum_tbl.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("BOX",           (0, 0), (-1, -1), 0.5, BLACK),
            ("INNERGRID",     (0, 0), (-1, -1), 0.3, RULE_GRAY),
            ("BACKGROUND",    (0, 0), (-1, 0),  LIGHT_GRAY),
            ("ALIGN",         (1, 1), (2, -1),  "RIGHT"),
        ]))
        story.append(sum_tbl)
        story.append(Spacer(1, 3 * mm))

    # ── Financial breakdown (FOB + freight + insurance = CIF) ────────────────
    fob_usd       = _safe_float(invoice_totals.get("total_fob_usd"))
    freight_usd   = _safe_float(invoice_totals.get("total_freight_usd"))
    insurance_usd = _safe_float(invoice_totals.get("total_insurance_usd"))
    total_qty = sum(ln["quantity"] for ln in lines)
    # Grand total is the customs value (CIF). Fall back to sum of line totals
    # only when CIF is unavailable.
    grand_total_usd = cif_usd or sum(ln["line_total_usd"] for ln in lines)

    if fob_usd is not None or freight_usd is not None or insurance_usd is not None:
        breakdown_rows = []
        if fob_usd is not None:
            breakdown_rows.append([
                Paragraph("Wartość FOB / FOB Value:", SUBTOT_S),
                Paragraph("USD {:,.2f}".format(fob_usd), SUBTOT_S),
            ])
        if freight_usd is not None:
            breakdown_rows.append([
                Paragraph("Fracht / Freight:", SUBTOT_S),
                Paragraph("USD {:,.2f}".format(freight_usd), SUBTOT_S),
            ])
        if insurance_usd is not None:
            breakdown_rows.append([
                Paragraph("Ubezpieczenie / Insurance:", SUBTOT_S),
                Paragraph("USD {:,.2f}".format(insurance_usd), SUBTOT_S),
            ])
        if breakdown_rows:
            breakdown_tbl = Table(breakdown_rows, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
            breakdown_tbl.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
            ]))
            story.append(breakdown_tbl)

    # ── Grand total (uses CIF customs value) ──────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=BLACK, spaceAfter=2))
    grand_tbl = Table(
        [[
            Paragraph("RAZEM CIF / TOTAL CIF (customs value):", GRAND_S),
            Paragraph("{:.0f} PCS  |  USD {:,.2f}".format(total_qty, grand_total_usd), GRAND_S),
        ]],
        colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5],
    )
    grand_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (1, 0), (1, 0),   "RIGHT"),
    ]))
    story.append(grand_tbl)

    # ── Signature block ───────────────────────────────────────────────────────
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_GRAY, spaceAfter=3))
    sig_hdr_tbl = Table(
        [[
            Paragraph("Podpis osoby upoważnionej / Authorised signature:", SIG_LBL),
            Paragraph("Data / Date:", SIG_LBL),
        ]],
        colWidths=[CONTENT_W * 0.62, CONTENT_W * 0.38],
    )
    sig_hdr_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(sig_hdr_tbl)
    sig_line_tbl = Table(
        [[
            Paragraph("_" * 55, SIG_LBL),
            Paragraph("_" * 32, SIG_LBL),
        ]],
        colWidths=[CONTENT_W * 0.62, CONTENT_W * 0.38],
    )
    sig_line_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    story.append(sig_line_tbl)

    # ── Legal footer ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_GRAY, spaceAfter=4))
    story.append(Paragraph(
        "Niniejszy dokument stanowi opis towarów przygotowany przez importera na potrzeby odprawy celnej. "
        "Opis oparty jest na fakturach handlowych wystawionych przez nadawcę. "
        "Ostateczna klasyfikacja taryfowa leży w kompetencji organu celnego. / "
        "This document is a goods description prepared by the importer for customs clearance purposes. "
        "Based on commercial invoices issued by the shipper. Final tariff classification rests with customs authority.",
        FOOTER,
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Estrella Jewels Sp. z o.o. Sp.k. | NIP: 5252812119  |  "
        "Wygenerowano / Generated: {}".format(gen_ts),
        FOOTER,
    ))

    doc.build(story)

    with open(output_path, "rb") as f:
        pdf_hash = hashlib.sha256(f.read()).hexdigest()

    return {
        "generated":       True,
        "output_path":     output_path,
        "filename":        filename,
        "items_described": len(lines),
        "pdf_hash":        pdf_hash,
        "error":           None,
    }


# ── Combined package generator ─────────────────────────────────────────────────

def generate_customs_description_package(
    batch: dict,
    awb: str,
    output_dir: str,
    dhl_email_id: str = "",
    date_override: Optional[str] = None,
    *,
    consignee_name: Optional[str] = None,
    consignor_name: Optional[str] = None,
) -> dict:
    """
    Generate both the Polish description PDF and the SAD-ready JSON in one call.
    Returns a combined result envelope suitable for the DHL clearance handler.

    Parameters
    ----------
    batch         : batch audit dict
    awb           : AWB number
    output_dir    : directory to write both files
    dhl_email_id  : optional DHL email ID for audit
    date_override : YYYY-MM-DD (defaults to today UTC)
    consignee_name: forwarded to generate_polish_description_pdf(); see its
                    docstring. None = flag_off (current hardcoded constant).
    consignor_name: forwarded to generate_polish_description_pdf(); see its
                    docstring. None = flag_off (current batch-parse behavior).

    Returns
    -------
    dict with keys:
        pdf   : result from generate_polish_description_pdf()
        json  : result from generate_sad_ready_json()
        audit : combined audit envelope
    """
    pdf_result  = generate_polish_description_pdf(
        batch, awb, output_dir, dhl_email_id=dhl_email_id, date_override=date_override,
        consignee_name=consignee_name,
        consignor_name=consignor_name,
    )
    json_result = generate_sad_ready_json(
        batch, awb, output_dir, dhl_email_id=dhl_email_id,
    )

    batch_id = (
        batch.get("batch_id") or
        (batch.get("batch_meta") or {}).get("batch_id") or
        ""
    )

    audit_envelope = {
        "awb":                 re.sub(r"\s+", "", awb),
        "batch_id":            batch_id,
        "dhl_email_id":        dhl_email_id,
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "source_invoice_hash": _compute_source_hash(batch),
        "pdf_hash":            pdf_result.get("pdf_hash"),
        "json_hash":           json_result.get("json_hash"),
        "approved_by":         None,
        "approved_at":         None,
    }

    return {
        "pdf":   pdf_result,
        "json":  json_result,
        "audit": audit_envelope,
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _extract_invoice_refs_from_names(batch: dict) -> list[str]:
    """
    Parse the leading numeric token from each entry in audit['invoice_names'].
    E.g. "121 Invoice EJL-26-27-121-04-05-26.pdf" → "121".
    Falls back to the truncated stem when no leading numeric token is found.
    Returns [] when invoice_names is absent.
    """
    names = batch.get("invoice_names") or []
    refs: list[str] = []
    for name in names:
        stem = Path(name).stem
        token = stem.split()[0] if stem.split() else stem
        if re.match(r"^\d+$", token):
            refs.append(token)
        else:
            refs.append(stem[:40])
    return refs


def _extract_invoices(batch: dict) -> list[dict]:
    """Pull the invoices list from wherever it lives in the batch dict."""
    result = batch.get("result") or batch
    # Try result.invoices
    if isinstance(result, dict):
        invs = result.get("invoices")
        if isinstance(invs, list):
            return invs
    # Try top-level invoices
    invs = batch.get("invoices")
    if isinstance(invs, list):
        return invs
    # Try rows with invoice grouping
    rows = (batch.get("result") or {}).get("rows") or batch.get("rows") or []
    if rows:
        # Group rows by invoice_number into synthetic invoice dicts
        inv_map: dict[str, list] = defaultdict(list)
        for r in rows:
            inv_no = r.get("invoice_number") or r.get("invoice_no") or "unknown"
            inv_map[inv_no].append(r)
        return [
            {"invoice_number": k, "items": v}
            for k, v in inv_map.items()
        ]
    return []


def _build_synthetic_lines_from_totals(batch: dict) -> list[dict]:
    """
    Build synthetic invoice lines from audit.json invoice_totals.product_counts
    when no structured line data is available.

    This is the last-resort fallback — it produces one line per product type
    with aggregate quantities and values.
    """
    invoice_totals = batch.get("invoice_totals") or {}
    cif_usd = _safe_float(invoice_totals.get("total_cif_usd")) or 0.0
    fob_usd = _safe_float(invoice_totals.get("total_fob_usd")) or cif_usd

    product_counts = invoice_totals.get("product_counts") or {}
    product_by_unit = invoice_totals.get("product_counts_by_unit") or {}

    # Map product_counts keys → item type keys used by ITEM_TYPE_PL
    KEY_MAP = {
        "rings":           "RING",
        "earrings":        "EARRINGS",
        "pendants":        "PENDANT",
        "bracelets":       "BRACELET",
        "necklaces":       "NECKLACE",
        "cufflinks":       "CUFFLINKS",
        "other_jewellery": "SET",
    }

    # Determine CN code / purity from customs_declaration if present
    customs = batch.get("customs_declaration") or {}
    cn_code = str(customs.get("cn_code") or "")
    goods_desc = str(customs.get("goods_description") or "")

    # Infer purity from goods_description (e.g. "BIŻUTERIA ZŁOTA PRÓBY" → gold, but no karat)
    purity_raw = ""
    desc_up = goods_desc.upper()
    if "ZŁOTA" in desc_up or "GOLD" in desc_up:
        # Default to 14KT if we can't determine; better than nothing
        purity_raw = "14KT"
    elif "SREBRA" in desc_up or "SILVER" in desc_up:
        purity_raw = "925"

    total_items = sum(max(0, v) for v in product_counts.values())
    if total_items == 0:
        return []

    # Prefer real invoice refs: inputs.invoice_refs → invoice_names parsing.
    # When multiple refs exist we DO NOT have per-invoice attribution at this
    # fallback level. We synthesize per-invoice rows by distributing each
    # item-type quantity across the invoice list using deterministic integer
    # divmod (first `remainder` invoices receive base+1, rest receive base).
    # The aggregate type-level totals are restored in the consolidated
    # summary section the renderer adds at the bottom of the document; the
    # per-invoice blocks exist for customs structural clarity.
    inv_refs = (
        (batch.get("inputs") or {}).get("invoice_refs")
        or _extract_invoice_refs_from_names(batch)
        or []
    )
    inv_refs = [str(r) for r in inv_refs]

    # When we have multiple invoice refs, each item type's qty is distributed
    # across them using divmod. A "single-invoice or no-refs" case behaves as
    # before (one row per type, full quantity).
    n_inv = len(inv_refs) if inv_refs else 1
    targets = inv_refs if inv_refs else [""]

    lines: list[dict] = []
    order = 0
    for prod_key, count in product_counts.items():
        if not count or count <= 0:
            continue
        itype = KEY_MAP.get(prod_key, "SET")

        # Determine UOM from product_counts_by_unit
        uom = "PCS"
        for unit_code, unit_counts in product_by_unit.items():
            if prod_key in unit_counts and unit_counts[prod_key] > 0:
                uom = unit_code.upper()
                break

        # Synthetic description like "14KT Gold Jewellery RING"
        purity_label = purity_raw if purity_raw else ""
        raw_desc = f"{purity_label} Gold Jewellery {itype}".strip() if purity_label else f"Gold Jewellery {itype}"

        norm = normalize_item_description(raw_desc, item_type=itype)

        # Type-level value (proportional to type qty in total_items, FOB-based).
        prop = count / total_items
        type_val = round(fob_usd * prop, 2)
        unit_p   = round(type_val / count, 2) if count else 0.0

        # divmod split across invoices for THIS item type
        base = int(count) // n_inv
        rem  = int(count) %  n_inv
        for i, inv_no in enumerate(targets):
            inv_qty = base + (1 if i < rem else 0)
            if inv_qty <= 0:
                continue
            order += 1
            line_val = round(unit_p * inv_qty, 2)
            lines.append({
                "line_order":                     order,
                "invoice_number":                 str(inv_no),
                "original_description":           raw_desc,
                "normalized_english_description": norm["normalized_english"],
                "polish_customs_description":     norm["polish_customs_description"],
                "item_type":                      norm["item_type"],
                "item_type_pl":                   norm["item_type_pl"],
                "material":                       norm["material_pl"],
                "gold_purity":                    norm["gold_purity_raw"],
                "stones":                         norm["stones_pl"],
                "natural_or_lab_grown":           norm["natural_or_lab"],
                "purpose":                        norm["purpose_pl"],
                "hs_candidate":                   norm["hs_candidate"],
                "hsn_from_invoice":               cn_code[:8] if cn_code else "",
                "classification_confidence":      norm["classification_confidence"],
                "classification_flag":            norm["classification_flag"],
                "classification_note":            norm["classification_note"],
                "quantity":                       float(inv_qty),
                "uom":                            uom,
                "gross_weight_g":                 None,
                "net_weight_g":                   None,
                "value_usd":                      unit_p,
                "line_total_usd":                 line_val,
            })

    return lines


def _consolidate_by_type(lines: list[dict]) -> list[dict]:
    """
    Group SAD-ready lines by item_type.
    Returns sorted list of group dicts for PDF rendering.
    """
    groups: dict[str, dict] = {}
    for line in lines:
        it = line.get("item_type") or "UNKNOWN"
        if it not in groups:
            groups[it] = {
                "item_type":                  it,
                "item_type_pl":               line.get("item_type_pl", "Wyrób jubilerski"),
                "polish_customs_description": line.get("polish_customs_description", ""),
                "material_pl":                line.get("material", ""),
                "purpose_pl":                 line.get("purpose", "Ozdoba — biżuteria do noszenia."),
                "total_qty":                  0.0,
                "total_value_usd":            0.0,
            }
        grp = groups[it]
        grp["total_qty"]       += (line.get("quantity") or 0.0)
        grp["total_value_usd"] += (line.get("line_total_usd") or 0.0)
        # Use first-seen description (most representative)
        if not grp["polish_customs_description"] and line.get("polish_customs_description"):
            grp["polish_customs_description"] = line["polish_customs_description"]

    return sorted(groups.values(), key=lambda g: g["item_type"])


def _get_exporter(batch: dict) -> str:
    """Extract exporter/seller name from batch dict."""
    for inv in _extract_invoices(batch):
        for key in ("exporter_name", "seller_name", "supplier_name"):
            v = inv.get(key)
            if v:
                return str(v)
    zc429 = (batch.get("result") or {}).get("zc429") or batch.get("zc429") or {}
    if isinstance(zc429, dict):
        v = zc429.get("exporter_name") or zc429.get("seller")
        if v:
            return str(v)
    return ""


def _compute_source_hash(batch: dict) -> str:
    """Compute SHA256 of the audit.json path content (or batch dict itself)."""
    audit_path = batch.get("_audit_path")
    if audit_path:
        p = Path(audit_path)
        if p.exists():
            return hashlib.sha256(p.read_bytes()).hexdigest()
    # Fallback: hash the batch dict
    content = json.dumps(batch, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _fmt_date_pl(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD.MM.YYYY."""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d")
        return d.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Quick smoke test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import tempfile

    print("=== customs_description_engine — self-test ===\n")

    cases = [
        ("14KT RING DIA&CLS",     ""),
        ("18KT EARRINGS LGD",     ""),
        ("925 SILVER BANGLE PLAIN", ""),
        ("14KT PENDANT DIA",      ""),
        ("18KT WHITE GOLD BRACELET CZ", ""),
        ("SL925 SILVER Plain Jewellery NECKLACE", "NECKLACE"),
    ]

    print("── normalize_item_description() ──")
    for raw, itype in cases:
        r = normalize_item_description(raw, itype)
        print(f"  Input : {raw!r}")
        print(f"  Polish: {r['polish_customs_description']}")
        print(f"  Eng   : {r['normalized_english']}")
        print(f"  Lab   : {r['natural_or_lab']}")
        print()

    print("── process_batch_items() ──")
    fake_batch = {
        "invoices": [
            {
                "invoice_number": "1295",
                "exporter_name":  "Estrella Jewels LLP.",
                "items": [
                    {"description": "14KT RING DIA&CLS",    "item_type": "RING",     "quantity": 2,  "unit_price": 213.50, "line_total": 427.00},
                    {"description": "18KT EARRINGS LGD",    "item_type": "EARRINGS", "quantity": 4,  "unit_price": 150.00, "line_total": 600.00},
                    {"description": "925 SILVER BANGLE PLAIN", "item_type": "BANGLE", "quantity": 1, "unit_price": 45.00,  "line_total": 45.00},
                    {"description": "Total Freight",         "item_type": "",         "quantity": 0,  "unit_price": 0,      "line_total": 0},
                ],
            },
            {
                "invoice_number": "1296",
                "items": [
                    {"description": "14KT PENDANT DIA",     "item_type": "PENDANT",  "quantity": 3,  "unit_price": 90.00,  "line_total": 270.00},
                ],
            },
        ],
    }

    lines = process_batch_items(fake_batch)
    print(f"  Lines produced: {len(lines)}  (should be 4, not 5 — freight skipped)")
    for l in lines:
        print(f"    [{l['line_order']}] {l['item_type']:10s} | {l['polish_customs_description'][:60]}")

    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = generate_customs_description_package(
            batch        = fake_batch,
            awb          = "3283625844",
            output_dir   = tmpdir,
            dhl_email_id = "MSG_001",
            date_override= "2026-04-26",
        )
        print("── generate_customs_description_package() ──")
        print(f"  PDF generated : {pkg['pdf']['generated']}")
        print(f"  PDF filename  : {pkg['pdf']['filename']}")
        print(f"  PDF hash      : {(pkg['pdf']['pdf_hash'] or '')[:16]}…")
        print(f"  JSON generated: {pkg['json']['generated']}")
        print(f"  JSON filename : {pkg['json']['filename']}")
        print(f"  JSON hash     : {(pkg['json']['json_hash'] or '')[:16]}…")
        print(f"  Items types   : {pkg['pdf']['items_described']}")

    print("\n=== Done ===")
