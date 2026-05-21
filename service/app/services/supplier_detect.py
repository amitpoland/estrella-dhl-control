"""
supplier_detect.py — Identify supplier from raw document text.

Pure function — no I/O, no state.  Used by both invoice and packing
intake hooks to route to the correct parser.

Canonical supplier codes
------------------------
``"global_jewellery"``  — Global Jewellery Pvt. Ltd. (Mumbai / India)
``None``                — Unknown / EJL (default EJL path)
"""
from __future__ import annotations

import re
from typing import Optional

# ── Patterns ──────────────────────────────────────────────────────────────────

_GLOBAL_JEWELLERY_RE = re.compile(
    r"Global\s+Jewellery\s+Pvt\.?\s*Ltd",
    re.IGNORECASE,
)


# ── Public API ────────────────────────────────────────────────────────────────

def detect_supplier(text: str) -> Optional[str]:
    """Return canonical supplier code or ``None`` if not recognised.

    Parameters
    ----------
    text:
        Raw text from a PDF page, Excel preamble rows, or filename.
        Callers should pass at most the first 1 000 characters for
        performance — the supplier name always appears near the top.

    Returns
    -------
    ``"global_jewellery"`` if the text matches Global Jewellery Pvt. Ltd.
    ``None`` for all other suppliers (EJL / unknown → default EJL path).
    """
    if _GLOBAL_JEWELLERY_RE.search(text or ""):
        return "global_jewellery"
    return None
