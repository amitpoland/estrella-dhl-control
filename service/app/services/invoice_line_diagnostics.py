"""invoice_line_diagnostics.py — pure deterministic line-description checks.

Detects parser regressions where invoice line descriptions look like the
overall invoice header / customs goods description instead of the
per-position line text.  Emits structured warning codes per line and at
the document level, never blocks intake.

This module is intentionally PURE:
  - no DB access
  - no HTTP / wFirma / PZ / DHL / posting calls
  - does not mutate the input list
  - deterministic: same input → same output (modulo `evaluated_at`)

Severity tiers (mapped from warning codes):
  error → flips requires_manual_review on the document
  warn  → flips requires_manual_review on the document
  info  → diagnostics only, no review flag

Warning codes (see evaluate_invoice_lines docstring for triggers):
  missing_line_description              (warn)
  header_description_used_as_line       (error)
  suspicious_repeated_line_description  (warn)
  mixed_category_description            (warn)
  looks_like_header_description         (warn)
  line_description_unusually_long       (info)

Used by routes_intake.py right after invoice_intake_parser.parse_invoice_pdf
returns.  The caller persists this dict via the intake storage layer's
merge_document_normalized_json helper (no schema change).
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


# ── Canonical jewelry item-type tokens (singular ∪ plural) ──────────────────
_CATEGORY_TOKENS: tuple = (
    "RING", "RINGS",
    "PENDANT", "PENDANTS",
    "EARRING", "EARRINGS",
    "BRACELET", "BRACELETS", "BANGLE", "BANGLES",
    "NECKLACE", "NECKLACES",
    "CHAIN", "CHAINS",
    "CUFFLINK", "CUFFLINKS",
)

# Map plural / variant → canonical singular for mixed-category counting.
_CATEGORY_CANON: Dict[str, str] = {
    "RING":      "RING",      "RINGS":     "RING",
    "PENDANT":   "PENDANT",   "PENDANTS":  "PENDANT",
    "EARRING":   "EARRINGS",  "EARRINGS":  "EARRINGS",
    "BRACELET":  "BRACELET",  "BRACELETS": "BRACELET",
    "BANGLE":    "BRACELET",  "BANGLES":   "BRACELET",
    "NECKLACE":  "NECKLACE",  "NECKLACES": "NECKLACE",
    "CHAIN":     "CHAIN",     "CHAINS":    "CHAIN",
    "CUFFLINK":  "CUFFLINK",  "CUFFLINKS": "CUFFLINK",
}

_KARAT_RE = re.compile(r"\b(?:09|10|14|18|22|24)\s*KT\b", re.IGNORECASE)
_PT_RE    = re.compile(r"\bPT\s*\d{3}\b",                 re.IGNORECASE)
_SILVER_RE = re.compile(r"\b(SL|SLV|SILV)\s*\d{3}\b",     re.IGNORECASE)

_SCHEMA_VERSION  = "1"
_KIND            = "invoice_line_description_diagnostics"

# Thresholds (kept module-local for easy tuning).
_LONG_DESC_LEN_FOR_REPEATS = 120   # min length to flag cross-line repetition
_UNUSUALLY_LONG_LEN        = 220   # info-level warning threshold
_LOOKS_LIKE_HEADER_MIN_LEN = 80
_LOOKS_LIKE_HEADER_MIN_SLASHES = 3
_LOOKS_LIKE_HEADER_MIN_KARAT_OR_METAL = 2
_HEADER_EQUALS_RATIO       = 0.95   # near-equality threshold for header check


def _canonical_categories(desc: str) -> set:
    """Return the set of canonical item-type tokens present in `desc`."""
    if not desc:
        return set()
    tokens = re.findall(r"[A-Z][A-Z]+", str(desc).upper())
    out = set()
    for t in tokens:
        if t in _CATEGORY_CANON:
            out.add(_CATEGORY_CANON[t])
    return out


def _karat_or_metal_hits(desc: str) -> int:
    if not desc:
        return 0
    return (len(_KARAT_RE.findall(desc))
            + len(_PT_RE.findall(desc))
            + len(_SILVER_RE.findall(desc)))


def _looks_like_header(desc: str) -> bool:
    """Heuristic for multi-category header text.

    True when ALL of the following hold:
      - length >= 80 chars
      - >= 3 forward-slash separators
      - >= 2 karat/metal tokens (signals multi-purity aggregation)
      - the trailing token is NOT a single canonical singular item type
        (e.g. ends with 'Jewellery' rather than 'RING' / 'PENDANT')
    """
    if not desc or len(desc) < _LOOKS_LIKE_HEADER_MIN_LEN:
        return False
    if desc.count("/") < _LOOKS_LIKE_HEADER_MIN_SLASHES:
        return False
    if _karat_or_metal_hits(desc) < _LOOKS_LIKE_HEADER_MIN_KARAT_OR_METAL:
        return False
    # Final non-whitespace token: prefer a canonical singular at the tail.
    tail_tokens = re.findall(r"[A-Z][A-Z]+", desc.upper())
    if tail_tokens and _CATEGORY_CANON.get(tail_tokens[-1], "") in (
        "RING", "PENDANT", "EARRINGS", "BRACELET",
        "NECKLACE", "CHAIN", "CUFFLINK",
    ):
        return False
    return True


def _near_equals(a: str, b: str, ratio: float = _HEADER_EQUALS_RATIO) -> bool:
    """Length-bounded fuzzy equality.  True when both strings exceed 20
    chars and their normalized forms either match exactly OR one is a
    long prefix/contained substring of the other meeting `ratio`.

    Used for the customs-header equality check — avoids both extremes:
    overly strict char-for-char compare (operator may have re-typed),
    and overly loose Levenshtein (slow + harder to predict)."""
    a_n = " ".join((a or "").lower().split())
    b_n = " ".join((b or "").lower().split())
    if not a_n or not b_n:
        return False
    if len(a_n) < 20 or len(b_n) < 20:
        return False
    if a_n == b_n:
        return True
    if a_n in b_n and len(a_n) / len(b_n) >= ratio:
        return True
    if b_n in a_n and len(b_n) / len(a_n) >= ratio:
        return True
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def evaluate_invoice_lines(
    lines: Sequence[Dict[str, Any]],
    *,
    customs_goods_description: str = "",
) -> Dict[str, Any]:
    """Run the per-invoice diagnostics suite.

    Parameters
    ----------
    lines
        The parsed invoice lines about to be persisted via
        the intake invoice-lines storage path.  Each dict carries
        ``line_position``, ``product_code``, ``description``.  The input
        is treated as read-only.
    customs_goods_description
        Optional customs/AWB header text for the same shipment.  When
        non-empty, line descriptions are checked for near-equality
        against this value to detect parser confusion.  When empty, the
        equality check is skipped silently (NOT a warning by itself).

    Returns
    -------
    dict
        ``{kind, schema_version, any_warning, requires_manual_review,
        doc_warnings, line_warnings, evaluated_at}``.  Severity for each
        line_warnings entry is the highest of its ``codes`` per the
        module-level severity table.

    Pure / deterministic / side-effect free.  No DB / HTTP / wFirma.
    """
    line_count = len(lines or [])

    # Build the cross-line repetition counter once (uses the *normalized*
    # description so trailing whitespace / case variants don't fool it).
    desc_counter: Counter = Counter()
    for ln in (lines or []):
        d = str((ln or {}).get("description") or "").strip()
        if d:
            desc_counter[d.lower()] += 1

    line_warnings: List[Dict[str, Any]] = []
    doc_warnings:  List[str]            = []
    any_warn = False
    any_review_flip = False

    cust = (customs_goods_description or "").strip()

    for ln in (lines or []):
        ln = dict(ln or {})    # local copy — never mutate caller input
        pos  = int(ln.get("line_position") or 0)
        pc   = str(ln.get("product_code")  or "").strip()
        desc = str(ln.get("description")   or "")
        desc_s = desc.strip()
        codes: List[str] = []

        # 1) missing
        if desc_s == "":
            codes.append("missing_line_description")

        # 2) header equality
        if cust and desc_s and _near_equals(desc_s, cust):
            codes.append("header_description_used_as_line")

        # 3) repeated long description
        if (len(desc_s) > _LONG_DESC_LEN_FOR_REPEATS
                and line_count > 1
                and desc_counter[desc_s.lower()] > 1):
            codes.append("suspicious_repeated_line_description")

        # 4) mixed categories
        cats = _canonical_categories(desc)
        if len(cats) >= 2:
            codes.append("mixed_category_description")

        # 5) looks like header
        if _looks_like_header(desc):
            codes.append("looks_like_header_description")

        # 6) unusually long
        if len(desc) > _UNUSUALLY_LONG_LEN:
            codes.append("line_description_unusually_long")

        if not codes:
            continue

        # Severity = highest tier present.
        if "header_description_used_as_line" in codes:
            severity = "error"
        elif any(c in codes for c in (
            "missing_line_description",
            "suspicious_repeated_line_description",
            "mixed_category_description",
            "looks_like_header_description",
        )):
            severity = "warn"
        else:
            severity = "info"

        any_warn = True
        if severity in ("warn", "error"):
            any_review_flip = True

        line_warnings.append({
            "line_position": pos,
            "product_code":  pc,
            "severity":      severity,
            "codes":         codes,
        })

    return {
        "kind":                   _KIND,
        "schema_version":         _SCHEMA_VERSION,
        "any_warning":            bool(any_warn),
        "requires_manual_review": bool(any_review_flip),
        "doc_warnings":           doc_warnings,
        "line_warnings":          line_warnings,
        "evaluated_at":           _now_iso(),
    }
