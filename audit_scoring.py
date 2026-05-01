#!/usr/bin/env python3
"""
audit_scoring.py — Deterministic audit risk scoring (0–100)
============================================================
Takes the structured check dicts from audit_agent and returns a numeric
score, risk level, and list of failed check keys.

Scoring model: start at 100, subtract penalty for each confirmed failure.
Gaps (None = could not verify) do NOT penalise — only confirmed False does.

Used by:
    audit_agent.build_audit_report()  → computes + returns score
    audit_pdf.generate_audit_pdf()    → renders score in memo
    routes_bot._process_bot_batch()   → triggers escalation if HIGH RISK
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple

# ── Weight table (must sum ≤ 100) ─────────────────────────────────────────────
WEIGHTS: Dict[str, int] = {
    "identity_mismatch":     30,  # exporter/importer name or NIP confirmed False
    "invoice_missing":       25,  # invoice ref mismatch SAD ↔ PDF (False, not None)
    "value_mismatch":        20,  # CIF total invoice vs SAD confirmed False
    "cif_formula_error":     10,  # FOB + F + I ≠ stated CIF on any invoice
    "transport_mismatch":    10,  # AWB confirmed not in SAD (False — rare)
    "address_inconsistency":  5,  # delivery address classification confirmed False
}

# These checks are ALWAYS penalised at full weight regardless of learning confidence.
# Learning cannot reduce their penalty — only human resolution can clear them.
HARD_LOCK_CHECKS = frozenset({
    "value_mismatch",
    "cif_formula_error",
    "invoice_missing",
})

_RISK_BANDS = [
    (90, "LOW RISK"),
    (70, "MEDIUM RISK"),
    (0,  "HIGH RISK"),
]


# ── Flag detection ────────────────────────────────────────────────────────────

def compute_flags(c1: dict, c2: dict, c3: dict, c4: dict, c5: dict, c6: dict) -> Dict[str, bool]:
    """
    Map check results to named penalty flags.
    Only confirmed False triggers a flag — None (gap) does not.
    """
    return {
        "identity_mismatch": (
            c1["result"] is False
            or c2["name_result"] is False
            or c2["nip_result"] is False
        ),
        "invoice_missing":       c4["result"] is False,
        "value_mismatch":        c5["cif_result"] is False,
        "cif_formula_error":     any(not ch["ok"] for ch in c5.get("per_inv_checks", [])),
        "transport_mismatch":    c6["result"] is False,
        "address_inconsistency": c3["consistent"] is False,
    }


# ── Score computation ─────────────────────────────────────────────────────────

def compute_audit_score(
    flags:       Dict[str, bool],
    confidences: Optional[Dict[str, float]] = None,
) -> Tuple[int, str]:
    """
    Subtract penalties for each active flag.

    When confidences are supplied (from learning_agent):
        penalty = weight × (1 − confidence)
    This reduces noise for known patterns while keeping hard-lock checks
    at full penalty (confidence is ignored for HARD_LOCK_CHECKS).

    Returns (score 0–100, risk_level string).
    """
    confidences = confidences or {}
    score = 100

    for key, weight in WEIGHTS.items():
        if not flags.get(key, False):
            continue
        if key in HARD_LOCK_CHECKS:
            # Hard lock: always full penalty, confidence irrelevant
            score -= weight
        else:
            conf    = max(0.0, min(1.0, confidences.get(key, 0.0)))
            penalty = round(weight * (1 - conf))
            score  -= penalty

    score = max(0, score)

    level = "HIGH RISK"
    for threshold, label in _RISK_BANDS:
        if score >= threshold:
            level = label
            break

    return score, level


def _penalty_breakdown(
    flags:       Dict[str, bool],
    confidences: Optional[Dict[str, float]] = None,
) -> Dict[str, dict]:
    """Return per-check penalty details for audit trace."""
    confidences = confidences or {}
    breakdown   = {}
    for key, weight in WEIGHTS.items():
        flagged = flags.get(key, False)
        if not flagged:
            breakdown[key] = {"flagged": False, "penalty": 0, "confidence": None}
            continue
        if key in HARD_LOCK_CHECKS:
            breakdown[key] = {
                "flagged": True, "penalty": weight, "confidence": None,
                "hard_locked": True,
            }
        else:
            conf    = max(0.0, min(1.0, confidences.get(key, 0.0)))
            penalty = round(weight * (1 - conf))
            breakdown[key] = {
                "flagged": True, "penalty": penalty,
                "confidence": round(conf, 3), "hard_locked": False,
            }
    return breakdown


# ── Public convenience ────────────────────────────────────────────────────────

def score_batch(
    c1: dict, c2: dict, c3: dict, c4: dict, c5: dict, c6: dict,
    confidences: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """
    Single call: compute flags + score + risk level + penalty breakdown.
    Pass confidences dict from learning_agent.AdjustmentResult to enable
    confidence-weighted scoring.

    Returns a dict suitable for storing in result["audit_score"].
    """
    flags        = compute_flags(c1, c2, c3, c4, c5, c6)
    score, level = compute_audit_score(flags, confidences)
    failed       = [k for k, v in flags.items() if v]
    breakdown    = _penalty_breakdown(flags, confidences)

    return {
        "score":            score,
        "risk_level":       level,
        "flags":            flags,
        "failed_checks":    failed,
        "penalty_breakdown": breakdown,
        "learning_applied": bool(confidences),
        "max_possible":     100,
        "weights":          dict(WEIGHTS),
    }
