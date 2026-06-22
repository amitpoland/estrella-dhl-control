"""
sales_packing_code_detection.py — Route sales packing list codes to the
correct fields (design_no vs order reference), ignoring non-product tokens.

Background
----------
Some client sales packing lists carry the real design/product code in the
DESCRIPTION column while the PRODUCT column is blank (—) or holds an EJL order
reference (EJL/26-27/NNN-N). The shared packing extractor maps DESCRIPTION →
``item_type`` and does not place the design code in ``design_no``, so the
``sales_packing_matcher`` (which is keyed on ``design_no``) cannot resolve the
canonical product_code from same-batch purchase evidence. Result: rows persist
with product_code='' and sales↔purchase linkage fails.

Authority model (confirmed with operator, 2026-06-22)
-----------------------------------------------------
In this system ``EJL/26-27/NNN-N`` is the CANONICAL product_code (purchase
invoice_lines + wFirma mapping); J/CSTN-style codes (e.g. ``J4006R01513``,
``CSTN00026``) are ``design_no``. Sales→purchase linkage is by ``design_no``.
So this module routes the real design code into ``design_no`` and any EJL
reference into ``order_ref``. It NEVER sets ``product_code`` — the
``sales_packing_matcher`` mints the canonical product_code from purchase
evidence (design_no is never used as a product_code fallback, per that module).

Non-product category tokens (PND, RNG, EAR, ...) describe item TYPE, never
identity, and are NEVER promoted to a design code: a row whose only code-like
token is a category stays unresolved (no product created/adopted) unless an
explicit mechanism (the gated PND price-tiebreak disambiguator, or an operator
correction) resolves it later.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple

# Item-category tokens (item TYPE, never product identity). Superset of both
# sales_packing_parser._CATEGORY_EN and sales_packing_matcher._CATEGORY_TOKENS
# so a category token in any column is never mistaken for a code. (All category
# tokens are digit-free, so they already fail the >=3-digit code test — this set
# is belt-and-braces + drives the category-superseded-by-description rule.)
CATEGORY_TOKENS = {
    "PND", "RNG", "EAR", "BRC", "BAN", "NEC", "BRO", "SET", "CHR", "CUF",
    "NCK", "BNG", "BRA", "PEN", "PDT", "CHN", "ANK", "NOSE", "TOE", "CUFF",
    "BCL", "CL", "MN",
}

# Annotation / reference prefixes that look code-like but are NOT design codes:
# sizes, weights, and proforma/invoice/order references. Rejected up front.
_NON_CODE_RE = re.compile(
    r"^(?:SIZE|PROF|INV|ORD|PO|EXP|WT|GW|NW)(?=[\d/\-.\s]|$)", re.IGNORECASE,
)

# EJL order / invoice-position reference, e.g. "EJL/26-27/299-1" or
# "EJL/26-27/299". Tolerant of surrounding/internal whitespace and an optional
# trailing "-N" line segment.
ORDER_REF_RE = re.compile(
    r"^\s*EJL\s*/\s*\d{2}\s*-\s*\d{2}\s*/\s*\d+(?:\s*-\s*\d+)?\s*$",
    re.IGNORECASE,
)

# "Blank" cell variants the source / extractor may leave behind.
_PLACEHOLDERS = {"", "—", "-", "–", "n/a", "na", "none", "null"}

# Real design/product code, e.g. J4006R01513, CSTN00026, JR04929, JE02341,
# JBR00254-1.50, J4502R00930-.04, JP02436, J4506P00551-S. Heuristic: a
# LETTER-LEADING alphanumeric token (optionally with -/. refinement suffixes)
# with >=3 digits. Leading-letter requirement excludes karat/carat/size
# annotations like "18KT2.50" / "0.75CT" (digit-leading); _NON_CODE_RE excludes
# letter-leading annotations like "SIZE12.5" / "PROF/001". Failure mode is
# benign: an unrecognised token is left unpromoted (design_no stays empty →
# row unresolved), never turned into a wrong product.
_CODE_BODY_RE   = re.compile(r"^[A-Za-z][A-Za-z0-9./\-]{3,}$")
_THREE_DIGITS_RE = re.compile(r"\d.*\d.*\d", re.DOTALL)


def is_order_ref(value: str) -> bool:
    """True when *value* is an EJL order / invoice-position reference."""
    return bool(ORDER_REF_RE.match(str(value or "")))


def is_category_token(value: str) -> bool:
    """True when *value* is a bare item-category token (PND/RNG/EAR/...)."""
    return str(value or "").strip().upper() in CATEGORY_TOKENS


def is_placeholder(value: str) -> bool:
    """True when *value* is blank or a dash/none placeholder."""
    return str(value or "").strip().lower() in _PLACEHOLDERS


def is_product_code(value: str) -> bool:
    """True when *value* looks like a real design/product code.

    Excludes blanks/placeholders, bare category tokens (PND/...), and EJL order
    references. Requires an alphanumeric token with at least one letter AND at
    least three digits so short category-like tokens never qualify.
    """
    s = str(value or "").strip()
    if is_placeholder(s) or is_category_token(s) or is_order_ref(s):
        return False
    if _NON_CODE_RE.match(s):
        return False
    if not _CODE_BODY_RE.match(s):
        return False
    return bool(_THREE_DIGITS_RE.search(s))


def normalize_sales_row_codes(row: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Route a parsed sales packing row's codes to the correct fields.

    Mutates and returns *row*, plus a short ``+``-joined classification string.

    Rules (operator-confirmed authority model):
      1. ``design_no`` holding an EJL order ref → move it to ``order_ref`` and
         clear ``design_no`` (an EJL ref is never the matcher's design key).
      2. ``design_no`` blank/placeholder + DESCRIPTION (``item_type``) is a real
         product code → promote ``item_type`` into ``design_no`` (matcher key).
      3. ``design_no`` blank + DESCRIPTION is an EJL ref → capture ``order_ref``.
      4. Category tokens (PND/...) are never promoted → the row stays
         unresolved (no product created/adopted).

    ``product_code`` is intentionally left untouched — the sales_packing_matcher
    is the sole authority that mints the canonical product_code from purchase
    evidence keyed on ``design_no``.
    """
    design    = str(row.get("design_no", "") or "").strip()
    desc      = str(row.get("item_type", "") or "").strip()   # DESCRIPTION → item_type
    order_ref = str(row.get("order_ref", "") or "").strip()
    notes = []

    # Rule 1 — an EJL ref must never sit in the design_no (matcher) slot.
    if design and is_order_ref(design):
        order_ref = order_ref or design
        design = ""
        notes.append("order_ref_from_design")

    # Rule 4b — a bare category token (PND/RNG/...) in the design slot is not
    # identity. Treat it as empty ONLY when DESCRIPTION supplies a real code
    # (direct match beats the price heuristic); otherwise keep it so the gated
    # PND price-tiebreak disambiguator can still run on a pure-PND row.
    if is_category_token(design) and is_product_code(desc):
        design = ""
        notes.append("category_token_superseded_by_description")

    if is_placeholder(design):
        design = ""

    # Rules 2/3/4 — fill an empty design_no from the DESCRIPTION column.
    if not design:
        if is_product_code(desc):
            design = desc
            notes.append("design_from_description")
        elif is_order_ref(desc):
            order_ref = order_ref or desc
            notes.append("order_ref_from_description")
        # category token / junk → leave design empty (Rule 4: ignore)

    row["design_no"] = design
    if order_ref:
        row["order_ref"] = order_ref
    return row, ("+".join(notes) or "unchanged")
