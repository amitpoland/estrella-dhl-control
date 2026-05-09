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
import logging
from typing import Dict, List, Optional, Tuple

# Module logger — shadow telemetry uses this. Production deployments should
# capture INFO-level logs from this module to collect HARDENING_SHADOW lines.
_log = logging.getLogger(__name__)

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


# ── Hard-link integrity ──────────────────────────────────────────────────────

def detect_hard_link_break(
    c4:  dict,
    c5:  dict,
    c6:  dict,
    hl:  Optional[dict] = None,
) -> Dict[str, object]:
    """
    Pure helper that decides whether a batch's hard-link evidence is broken
    (SAD ↔ invoice ↔ AWB ↔ CIF integrity has a *confirmed* failure).

    A hard-link break is recognised only on an explicit ``False`` result.
    ``None`` (could-not-verify) is NEVER a break — it's a verification gap,
    not a confirmed mismatch.

    Inspects:
      * ``c4["result"]``       — invoice ↔ SAD reference match
      * ``c5["cif_result"]``   — CIF total invoice vs SAD
      * ``c6["result"]``       — AWB ↔ SAD transport reference
      * ``hl``                 — optional pre-computed hard-link dict
                                  with ``any_broken`` marker and free-text
                                  ``reason`` string from upstream parsers

    Returns
    -------
    dict
        ``{"blocked": bool, "reasons": list[str]}``

        ``blocked`` is ``True`` if ANY of the above signals a confirmed
        failure. ``reasons`` is a list of stable human-readable strings
        naming each contributing failure (empty when not blocked). The
        reason strings are intentionally stable so callers can grep for
        a substring (e.g. ``"AWB"``, ``"cif_total"``) in tests and
        downstream UI without coupling to a specific phrasing.

    No I/O. No mutation of inputs.
    """
    reasons: List[str] = []

    if c4.get("result") is False:
        reasons.append(
            "invoice_ref_mismatch: invoice references not found in SAD"
        )
    if c5.get("cif_result") is False:
        reasons.append(
            "cif_total_mismatch: invoice CIF total != SAD CIF total"
        )
    if c6.get("result") is False:
        reasons.append(
            "awb_mismatch: AWB not found in SAD transport reference"
        )

    if hl is not None and hl.get("any_broken") is True:
        msg = (hl.get("reason") or "").strip() or "hard link broken"
        reasons.append(msg)

    return {"blocked": bool(reasons), "reasons": reasons}


# ── Audit hardening status taxonomy (feature-flagged) ────────────────────────
#
# The hardening path adds a categorical `status` field on top of the existing
# numeric score + risk_level, gated behind AUDIT_HARDENING_ENABLED.
#
# Status precedence (most severe first):
#     BLOCKED       → confirmed hard-link break (force score=0)
#     NOT_VERIFIED  → key check could not be verified (cap score≤70)
#     PARTIAL       → SAD-aggregated or partial evidence (cap score≤85)
#     VERIFIED      → fully verified, optionally with parser fallback
#                     (cap score≤90 when nip_source==sad_and_master)
#
# Caps only LOWER score; they never raise it. Force-zero overrides all caps.
# The legacy `risk_level` field stays unchanged for audit_pdf, escalation,
# Cliq, and API consumers — the new `status` field is purely additive.

import os as _os


def _hardening_enabled() -> bool:
    """Read the AUDIT_HARDENING_ENABLED feature flag at call time.

    Source-of-truth is the environment variable so audit_scoring.py works
    standalone (no service-side settings dependency). The mirror field
    `settings.audit_hardening_enabled` in service/app/core/config.py is
    the canonical service-side configuration; pydantic populates that field
    from the same env var, keeping the two in lock-step.
    """
    return _os.environ.get("AUDIT_HARDENING_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _resolve_hardening_status(
    score:      int,
    c1:         dict,
    c4:         dict,
    c5:         dict,
    c6:         dict,
    qty_status: Optional[str],
    cn_status:  Optional[str],
    nip_source: Optional[str],
) -> Tuple[int, str, str]:
    """Apply hardening caps + status taxonomy AFTER the legacy score is computed.

    Returns (final_score, final_risk_level, final_status). The caller decides
    whether to expose `status` in the public return dict; this helper just
    computes it.
    """
    # 1. BLOCKED — confirmed hard-link break forces score → 0.
    hl_result = detect_hard_link_break(c4, c5, c6)
    if hl_result["blocked"]:
        return 0, "HIGH RISK", "BLOCKED"

    # 2. NOT_VERIFIED — c1 (exporter or sad-value parsing) is None / missing.
    if c1.get("result") is None or c1.get("sad_value_present") is False:
        capped = min(score, 70)
        # Re-derive risk band from the capped score so the legacy field
        # stays internally consistent.
        level = "HIGH RISK"
        for threshold, label in _RISK_BANDS:
            if capped >= threshold:
                level = label
                break
        return capped, level, "NOT_VERIFIED"

    # 3. PARTIAL — SAD-aggregated quantity OR CN parent-aggregation.
    if (
        qty_status == "partial_aggregated_sad"
        or cn_status == "verified_parent_aggregated"
    ):
        capped = min(score, 85)
        level = "HIGH RISK"
        for threshold, label in _RISK_BANDS:
            if capped >= threshold:
                level = label
                break
        return capped, level, "PARTIAL"

    # 4. VERIFIED with parser fallback — invoice NIP missing, SAD NIP matches
    #    the master record. Slight confidence dock; caller still verified.
    if nip_source == "sad_and_master":
        capped = min(score, 90)
        level = "HIGH RISK"
        for threshold, label in _RISK_BANDS:
            if capped >= threshold:
                level = label
                break
        return capped, level, "VERIFIED"

    # 5. VERIFIED at the confidence-weighted score, no cap.
    level = "HIGH RISK"
    for threshold, label in _RISK_BANDS:
        if score >= threshold:
            level = label
            break
    return score, level, "VERIFIED"


# ── Public convenience ────────────────────────────────────────────────────────

def score_batch(
    c1: dict, c2: dict, c3: dict, c4: dict, c5: dict, c6: dict,
    confidences: Optional[Dict[str, float]] = None,
    *,
    qty_status: Optional[str] = None,
    cn_status:  Optional[str] = None,
    nip_source: Optional[str] = None,
) -> Dict[str, object]:
    """
    Single call: compute flags + score + risk level + penalty breakdown.
    Pass confidences dict from learning_agent.AdjustmentResult to enable
    confidence-weighted scoring.

    Hardening (feature-flagged): when ``AUDIT_HARDENING_ENABLED`` is true OR
    when any of ``qty_status`` / ``cn_status`` / ``nip_source`` is supplied,
    the return dict additionally carries a categorical ``status`` field
    (``"VERIFIED"``, ``"PARTIAL"``, ``"NOT_VERIFIED"``, or ``"BLOCKED"``)
    and the score is post-processed by ``_resolve_hardening_status`` to
    apply caps and BLOCKED-force-zero. The legacy ``risk_level`` field is
    preserved (and re-derived consistently from the capped score) so
    existing PDF, Cliq, and API consumers continue to work without change.

    Legacy path (flag off AND no categoricals supplied) returns the
    previous return shape exactly — no ``status`` key.

    Returns a dict suitable for storing in result["audit_score"].
    """
    flags        = compute_flags(c1, c2, c3, c4, c5, c6)
    score, level = compute_audit_score(flags, confidences)
    failed       = [k for k, v in flags.items() if v]
    breakdown    = _penalty_breakdown(flags, confidences)

    out: Dict[str, object] = {
        "score":            score,
        "risk_level":       level,
        "flags":            flags,
        "failed_checks":    failed,
        "penalty_breakdown": breakdown,
        "learning_applied": bool(confidences),
        "max_possible":     100,
        "weights":          dict(WEIGHTS),
    }

    # Hardening activation: gated SOLELY by the AUDIT_HARDENING_ENABLED
    # feature flag. Earlier revisions of this module also activated when
    # any categorical kwarg was non-None, but verify_sad_invoice_match
    # always emits non-None categoricals (commit 42ceb54), so the
    # categorical-trigger silently activated hardening for every
    # audit_agent batch — bypassing the flag's intended gate. The flag
    # is now the SINGLE source of truth for whether caps + force-zero
    # affect returned values.
    hardening_active = _hardening_enabled()

    # Always compute the *hypothetical* hardening result so we can either
    # apply it (when active) or shadow-log it (when dormant). This is
    # cheap (no I/O, just three branches in _resolve_hardening_status).
    capped_score, capped_level, status = _resolve_hardening_status(
        score, c1, c4, c5, c6, qty_status, cn_status, nip_source,
    )

    if hardening_active:
        # Active: apply caps and emit status.
        out["score"]      = capped_score
        out["risk_level"] = capped_level
        out["status"]     = status
    else:
        # Shadow: telemetry only. Returned score / risk_level untouched.
        # The shadow_* informational keys are additive — existing readers
        # of the score_batch return dict are unaffected (they read score,
        # risk_level, flags, failed_checks, penalty_breakdown,
        # learning_applied, max_possible, weights).
        out["shadow_status"]  = status
        out["shadow_score"]   = capped_score
        out["shadow_blocked"] = (status == "BLOCKED")

        # Structured log line for ops to grep / aggregate. Format is
        # stable so log shippers can parse without coupling to phrasing.
        _log.info(
            "HARDENING_SHADOW would_blocked=%s status=%s score=%s "
            "legacy_score=%s legacy_risk_level=%s",
            (status == "BLOCKED"),
            status,
            capped_score,
            score,
            level,
        )
    return out
