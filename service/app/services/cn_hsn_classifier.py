"""
cn_hsn_classifier.py — Pure comparison engine for EU CN ↔ India HSN.

Rationale
---------
HSN is the India / export-side classification. CN is the EU /
import-side Combined Nomenclature. The first 6 digits are the global
HS code and ARE comparable. The last 2 digits diverge by jurisdiction
— they are NOT comparable as a strict equality test.

The legacy customs engine emitted ``cn_match=False`` whenever the
8-digit codes weren't byte-equal. This produced false "blocked"
states for shipments where the SAD aggregates several invoice HSNs
under one CN, even though every line agrees at the heading or HS6
level.

This module replaces that strict equality with a hierarchy:

  exact_code_match   — full normalized codes equal
  hs6_match          — first 6 digits equal (global HS)
  heading_match      — first 4 digits equal (HS heading)
  chapter_match      — first 2 digits equal (HS chapter)
  different_chapter  — chapters differ (hard review/block)

For a SAD CN compared to a list of invoice HSNs, the worst per-line
result is the overall outcome. ``hs6_match`` and ``heading_match``
are non-fatal — they produce a *review note*, not a blocker.
``chapter_match`` is a soft block (operator decision required).
``different_chapter`` is a hard block.

Pure / read-only / no I/O. Imported by both readiness-style endpoints
and the operator-decision routes.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

LEVEL_EXACT     = "exact_code_match"
LEVEL_HS6       = "hs6_match"
LEVEL_HEADING   = "heading_match"
LEVEL_CHAPTER   = "chapter_match"
LEVEL_DIFFERENT = "different_chapter"
LEVEL_INVALID   = "invalid_input"

_RANK = {
    LEVEL_EXACT:     5,
    LEVEL_HS6:       4,
    LEVEL_HEADING:   3,
    LEVEL_CHAPTER:   2,
    LEVEL_DIFFERENT: 1,
    LEVEL_INVALID:   0,
}

# Levels at which the comparison must NOT block PZ on its own.
_NON_BLOCKING_LEVELS = frozenset({LEVEL_EXACT, LEVEL_HS6, LEVEL_HEADING})


def normalize(code: Any) -> str:
    """Strip non-digits. Returns the longest digit-only prefix-or-substring
    suitable for hierarchy comparison. Empty/invalid → ''."""
    if code is None:
        return ""
    return re.sub(r"\D", "", str(code))


def _level_for_pair(a: str, b: str) -> str:
    """Return the highest level at which two normalized codes agree."""
    if not a or not b:
        return LEVEL_INVALID
    if len(a) < 2 or len(b) < 2:
        return LEVEL_INVALID
    if a == b:
        return LEVEL_EXACT
    if len(a) >= 6 and len(b) >= 6 and a[:6] == b[:6]:
        return LEVEL_HS6
    if a[:4] == b[:4]:
        return LEVEL_HEADING
    if a[:2] == b[:2]:
        return LEVEL_CHAPTER
    return LEVEL_DIFFERENT


def compare_one(sad_cn: Any, invoice_hsn: Any) -> Dict[str, Any]:
    """Compare a single CN to a single HSN. Returns:
      { sad_cn, invoice_hsn, sad_cn_norm, invoice_hsn_norm, level }
    """
    a = normalize(sad_cn)
    b = normalize(invoice_hsn)
    return {
        "sad_cn":           sad_cn,
        "invoice_hsn":      invoice_hsn,
        "sad_cn_norm":      a,
        "invoice_hsn_norm": b,
        "level":            _level_for_pair(a, b),
    }


def classify(
    sad_cn:        Any,
    invoice_hsns:  Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Compare one SAD CN to a list of invoice HSNs.

    Result:
      {
        sad_cn,                str
        sad_cn_normalized,     str
        invoice_hsns,          [str]
        invoice_hsns_normalized,[str]
        per_line:              [ {invoice_hsn, level} … ],
        worst_level:           str,                  ← drives blocking
        is_blocking:           bool,
        is_review:             bool,                 ← chapter_match
        aggregation_detected:  bool,                 ← multiple distinct HSNs
        mixed_metals_detected: bool,                 ← e.g. 7113 11 + 7113 19
        recommendation:        str,
        notes:                 [str],
      }

    Decision matrix:
      - worst_level in {exact, hs6, heading}        → not blocking, review note
      - worst_level == chapter_match                → soft block, operator decision
      - worst_level == different_chapter            → hard block
      - worst_level == invalid_input                → review (cannot compare)
    """
    invoice_hsns = list(invoice_hsns or [])
    sad_norm     = normalize(sad_cn)
    norm_list    = [normalize(h) for h in invoice_hsns]
    notes: List[str] = []

    if not sad_norm:
        return {
            "sad_cn":                  sad_cn or "",
            "sad_cn_normalized":       "",
            "invoice_hsns":            invoice_hsns,
            "invoice_hsns_normalized": norm_list,
            "per_line":                [],
            "worst_level":             LEVEL_INVALID,
            "is_blocking":             False,
            "is_review":               True,
            "aggregation_detected":    False,
            "mixed_metals_detected":   False,
            "recommendation":          "review",
            "notes":                   ["SAD CN is empty — cannot compare."],
        }

    # If invoice has no HSNs, we can't compare — surface as review.
    if not invoice_hsns:
        return {
            "sad_cn":                  sad_cn,
            "sad_cn_normalized":       sad_norm,
            "invoice_hsns":            [],
            "invoice_hsns_normalized": [],
            "per_line":                [],
            "worst_level":             LEVEL_INVALID,
            "is_blocking":             False,
            "is_review":               True,
            "aggregation_detected":    False,
            "mixed_metals_detected":   False,
            "recommendation":          "review",
            "notes":                   ["No invoice HSN codes available — "
                                        "SAD CN cannot be cross-checked."],
        }

    per_line = [compare_one(sad_cn, h) for h in invoice_hsns]
    levels   = [r["level"] for r in per_line]

    # Worst (lowest-rank) level wins.
    worst = min(levels, key=lambda lv: _RANK.get(lv, 0))

    distinct_hsns      = {n for n in norm_list if n}
    aggregation        = len(distinct_hsns) > 1
    distinct_headings  = {n[:4] for n in norm_list if len(n) >= 4}
    distinct_hs6       = {n[:6] for n in norm_list if len(n) >= 6}
    # Mixed metals: in chapter 71, heading 7113 splits silver vs gold at
    # digit 5-6 (711311 silver, 711319 gold). So distinct hs6 within the
    # invoice signals mixed metal types under one aggregated SAD CN.
    mixed_metals       = len(distinct_hs6) > 1 or len(distinct_headings) > 1

    if aggregation:
        notes.append("SAD aggregates multiple invoice HSN codes under one CN.")
    if mixed_metals:
        notes.append("Invoice contains mixed HSN headings (e.g. silver vs gold) "
                     "while SAD uses one aggregated CN.")
    if worst in (LEVEL_HS6, LEVEL_HEADING):
        notes.append("CN/HSN differ only by national/EU extension or aggregation.")
    if worst == LEVEL_CHAPTER:
        notes.append("Codes share HS chapter but differ at heading. "
                     "Operator decision required.")
    if worst == LEVEL_DIFFERENT:
        notes.append("Codes belong to different HS chapters — hard block.")

    is_blocking = worst not in _NON_BLOCKING_LEVELS and worst != LEVEL_INVALID
    is_review   = worst != LEVEL_EXACT and worst != LEVEL_DIFFERENT

    if worst == LEVEL_EXACT:
        recommendation = "accept_compatible"
    elif worst in (LEVEL_HS6, LEVEL_HEADING):
        recommendation = "accept_with_note"
    elif worst == LEVEL_CHAPTER:
        recommendation = "operator_decision"
    elif worst == LEVEL_DIFFERENT:
        recommendation = "hard_block"
    else:
        recommendation = "review"

    return {
        "sad_cn":                  sad_cn,
        "sad_cn_normalized":       sad_norm,
        "invoice_hsns":            invoice_hsns,
        "invoice_hsns_normalized": norm_list,
        "per_line":                per_line,
        "worst_level":             worst,
        "is_blocking":             is_blocking,
        "is_review":               is_review,
        "aggregation_detected":    aggregation,
        "mixed_metals_detected":   mixed_metals,
        "recommendation":          recommendation,
        "notes":                   notes,
    }
