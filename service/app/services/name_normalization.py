"""
Name normalization consolidation module.

This module hosts seven distinct name-normalization implementations that were
originally scattered across the customer/supplier/contractor matching domain.
Each function is moved byte-identically from its original location to preserve
exact behavior while providing single ownership and routing.

Behavioral differences matrix (from Phase-0 inspection):
- customer_resolution_normalize_name: " ".join(s.strip().split()).lower() — None → ""
- proforma_normalize_client_name: re.sub(r"\s+", " ", raw.strip()) — case-preserving
- suppliers_db_normalize_name: lowercase → punct removal → whitespace collapse — no flags
- wfirma_auto_resolve_normalize_name: re.sub(r"\s+", " ", raw.strip()) — case-preserving (identical to #2)
- master_data_norm: lowercase → NFD accent strip → legal-suffix removal → whitespace collapse
- packing_contractor_normalise_name: NFKD+ASCII-fallback → lower → punct strip → legal-suffix removal → punct removal → whitespace collapse
- wfirma_sync_normalise_client_name: NFKC → whitespace collapse → trailing-punct removal → casefold

These functions are kept as distinct variants to preserve existing behavior.
Algorithm unification is explicitly out of scope.
"""

import re
import unicodedata
from typing import Optional


# ── Constants from suppliers_db.py ────────────────────────────────────────────

_PUNCT_RE = re.compile(r"[^\w\s]")   # for name normalization
_MULTI_SPACE_RE = re.compile(r"\s+")


# ── Constants from packing_contractor_resolver.py ─────────────────────────────

# ASCII fallback table for letters that NFKD doesn't decompose
_ASCII_FALLBACK = str.maketrans({
    "ł": "l",  "Ł": "L",
    "ø": "o",  "Ø": "O",
    "æ": "ae", "Æ": "AE",
    "å": "a",  "Å": "A",
    "ß": "ss",
    "œ": "oe", "Œ": "OE",
    "ð": "d",  "Ð": "D",
})

# Order matters — longer suffixes first so "Sp. z o.o." beats "z o.o."
# Patterns are matched as case-insensitive whole-word-or-end-of-string.
_LEGAL_SUFFIXES = (
    r"spółka z ograniczoną odpowiedzialnością",
    r"sp\.?\s*z\s*o\.?\s*o\.?",
    r"pvt\.?\s*ltd\.?",
    r"private\s+limited",
    r"s\.r\.o\.?",
    r"co\.?\s*,?\s*ltd\.?",
    r"co\.?\s*ltd\.?",
    r"limited",
    r"llp\.?",
    r"ltd\.?",
    r"gmbh",
    r"a\.?g\.?",
    r"s\.?a\.?s\.?",
    r"s\.?a\.?",
    r"b\.?v\.?",
    r"oy",
    r"ab",
    r"inc\.?",
    r"llc",
    r"eood",
    r"corp\.?",
)
_LEGAL_SUFFIXES_RE = re.compile(
    r"\b(?:" + "|".join(_LEGAL_SUFFIXES) + r")\b\s*\.?\s*$",
    re.IGNORECASE,
)


# ── Constants from wfirma_customer_sync.py ────────────────────────────────────

_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[\.,;:!\?]+$")


# ── Helper functions from packing_contractor_resolver.py ──────────────────────

def _strip_accents(s: str) -> str:
    """Strip combining accents AND apply manual ASCII fallback for letters
    NFKD does not decompose (Polish ł, Nordic ø/æ/å, German ß, etc.)."""
    nfkd = unicodedata.normalize("NFKD", s)
    base = "".join(c for c in nfkd if not unicodedata.combining(c))
    return base.translate(_ASCII_FALLBACK)


# ── The seven normalization functions ─────────────────────────────────────────

def customer_resolution_normalize_name(s: Optional[str]) -> str:
    """Case-insensitive whitespace-collapsed comparison key.

    Mirrors the lighter normalisation used by the existing name resolver
    in routes_proforma.py (``_normalize_client_name``) so the "names
    differ?" advisory test is consistent with the rest of the system.

    Source: service/app/services/customer_resolution_authority.py:60
    """
    if not s:
        return ""
    return " ".join(s.strip().split()).lower()


def proforma_normalize_client_name(raw: str) -> str:
    """Trim outer whitespace + collapse internal whitespace runs to a single
    space. Case is preserved here so the displayed name in diagnostics
    matches what the operator entered. The resolver's match step is
    case-insensitive separately.

    Source: service/app/api/routes_proforma.py:263
    """
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def suppliers_db_normalize_name(name: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace.

    Used for fuzzy supplier name matching between audit-resolved names
    (e.g. "Estrella Jewels LLP") and master-data canonical names
    (e.g. "ESTRELLA JEWELS LLP.").  Removes trailing periods and other
    punctuation so both normalise to "estrella jewels llp".

    Source: service/app/services/suppliers_db.py:429
    """
    if not name:
        return ""
    s = name.lower().strip()
    s = _PUNCT_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


def wfirma_auto_resolve_normalize_name(raw: str) -> str:
    """Strip outer whitespace and collapse internal whitespace to single
    space. Case is preserved in the returned form; comparison is done
    case-insensitively elsewhere.

    Source: service/app/services/wfirma_customer_auto_resolve.py:87
    """
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def master_data_norm(s: Optional[str]) -> str:
    """Normalize string for dedup: lowercase, NFD, strip legal suffixes.

    Source: service/app/services/master_data_intelligence.py:135
    """
    if not s:
        return ""
    t = unicodedata.normalize("NFD", s.lower().strip())
    # strip common legal entity suffixes for name-based dedup
    for suffix in (" sp z o.o.", " sp. z o.o.", " s.a.", " gmbh", " ltd", " llp",
                   " b.v.", " s.r.o.", " s.r.l.", " inc.", " inc", " corp."):
        if t.endswith(suffix):
            t = t[: -len(suffix)].strip()
    return re.sub(r"\s+", " ", t)


def packing_contractor_normalise_name(name: Optional[str]) -> str:
    """Operator-stable normalised key.

    1. lowercase
    2. strip accents
    3. drop punctuation (keep alphanumerics + spaces)
    4. drop legal-form suffixes ("Sp. z o.o.", "LLP", "GmbH", ...)
    5. collapse whitespace

    Empty / None → "".  Pure function, no I/O.

    Source: service/app/services/packing_contractor_resolver.py:112
    """
    if not name:
        return ""
    s = _strip_accents(str(name)).lower().strip()
    # Drop trailing non-word punctuation BEFORE suffix detection so that
    # "beta, GMBH!" reaches the suffix regex as "beta, gmbh".
    s = re.sub(r"[^\w\s,.\-]+$", "", s).strip()
    # Drop trailing legal suffix once or twice (handles "Co., Ltd." → "" path).
    for _ in range(2):
        before = s
        s = _LEGAL_SUFFIXES_RE.sub("", s).strip(" ,.;:-")
        if s == before:
            break
    # Drop punctuation except spaces.
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    # Collapse whitespace.
    s = re.sub(r"\s+", " ", s).strip()
    return s


def wfirma_sync_normalise_client_name(name: str) -> str:
    """
    Lossless-by-character (case-fold, NFKC, strip, collapse whitespace,
    drop trailing punctuation) so two near-duplicate spellings of the
    same contractor reconcile to the same key.

    Pure function — no side effects, no I/O. Called by classify_pair on
    BOTH the remote name and the local client_name before comparison.

    Source: service/app/services/wfirma_customer_sync.py:60
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip()
    s = _WHITESPACE.sub(" ", s)
    s = _TRAILING_PUNCT.sub("", s)
    return s.casefold()