"""
classifier.py — Product-type classification with last-noun authority.

Authority rule: the LAST item-type keyword in a commercial invoice
description is the final product noun. Descriptor words appearing
before the final noun (e.g. "Stud" in "Stud Jewell RING") do NOT
override the final noun.

    "Stud ... RING"    -> RING   (STUD is a style descriptor, not earring type)
    "Stud ... PENDANT" -> PENDANT
    "Gold Stud"        -> STUD   (only type keyword present, earrings correct)
    "18KT EARRINGS"    -> EARRINGS (no STUD present)

Read-only: no DB writes, no external calls.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# ── Item-type keyword table ────────────────────────────────────────────────────
# Each entry: (canonical_type, regex_pattern).
# Patterns are matched case-insensitively against the full description.
# All matches collected by position; the LAST match wins (final-noun authority).

ITEM_TYPE_ORDER: List[Tuple[str, str]] = [
    ("RING",      r"\bRING\b"),
    ("PENDANT",   r"\bPENDANT\b"),
    ("BRACELET",  r"\bBRACELET\b"),
    ("BANGLE",    r"\bBANGLE\b"),
    ("NECKLACE",  r"\bNECKLACE\b"),
    ("CHAIN",     r"\bCHAIN\b"),
    ("EARRINGS",  r"\bEARRINGS?\b"),
    ("BROOCH",    r"\bBROOCH\b"),
    ("CUFFLINK",  r"\bCUFFLINK\b"),
    # STUD must come after EARRINGS so that "Stud Earrings" resolves to EARRINGS.
    # When STUD is the LAST (or only) type keyword, it means stud earrings.
    ("STUD",      r"\bSTUD\b"),
]

_COMPILED = [(t, re.compile(p, re.IGNORECASE)) for t, p in ITEM_TYPE_ORDER]


def classify_product_type(description: str) -> str:
    """Return the canonical product type for *description*.

    Applies last-noun authority: all item-type keywords are found by position,
    and the one that appears last (rightmost) in the string wins.

    Returns "UNKNOWN" when no recognised keyword is present.

    Examples::

        >>> classify_product_type("PCS, 14KT Gold,LGD Gold Stud Jewell RING")
        'RING'
        >>> classify_product_type("14KT Gold Stud Style PENDANT DIA")
        'PENDANT'
        >>> classify_product_type("14KT Gold Stud Plain")
        'STUD'
        >>> classify_product_type("18KT EARRINGS LGD")
        'EARRINGS'
    """
    matches: List[Tuple[int, str]] = []
    for type_name, pattern in _COMPILED:
        for m in pattern.finditer(description):
            matches.append((m.start(), type_name))

    if not matches:
        return "UNKNOWN"

    # Sort by position; the last match (highest start offset) is the authority.
    matches.sort(key=lambda x: x[0])
    return matches[-1][1]


def is_stud_earring(description: str) -> bool:
    """True when the description resolves to stud earrings (STUD is the last type)."""
    return classify_product_type(description) == "STUD"
