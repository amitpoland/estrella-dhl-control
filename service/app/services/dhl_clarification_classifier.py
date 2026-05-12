"""
dhl_clarification_classifier.py — DHL inbound clarification intent classifier.

P0 SCAFFOLD ONLY. The production classifier ships its trained weights in P4.
At P0 this is a deterministic keyword-bag stub that:
  - emits one of four canonical intents OR "unknown"
  - reports a confidence in [0.0, 1.0]
  - never reaches network or external state

Canonical intents (locked at P0):
    goods_description  — DHL asks for HS code / commodity detail
    invoice            — DHL asks for invoice copy / commercial details
    authorization      — DHL asks for power of attorney / cesja / authorization
    sad_received       — DHL forwards the SAD/PZC clearance result

Unknown intent → operator-review fallback. The coordinator must never
auto-reply on `unknown` regardless of confidence.

Confidence thresholds for *acting* on the classification are NOT baked into
this module — they are read at call time from settings:
    settings.dhl_selfclearance_p4_classifier_min_confidence  (default 0.85)
    settings.dhl_selfclearance_p5_classifier_min_confidence  (default 0.95)

Phase callers (P4, P5) read the appropriate threshold and gate the action
before any irreversible side-effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

# ── Intents (frozen) ─────────────────────────────────────────────────────────

INTENT_GOODS_DESCRIPTION: str = "goods_description"
INTENT_INVOICE:           str = "invoice"
INTENT_AUTHORIZATION:     str = "authorization"
INTENT_SAD_RECEIVED:      str = "sad_received"
INTENT_UNKNOWN:           str = "unknown"

INTENTS: FrozenSet[str] = frozenset({
    INTENT_GOODS_DESCRIPTION,
    INTENT_INVOICE,
    INTENT_AUTHORIZATION,
    INTENT_SAD_RECEIVED,
    INTENT_UNKNOWN,
})

ACTIONABLE_INTENTS: FrozenSet[str] = INTENTS - {INTENT_UNKNOWN}


# ── Classifier output ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ClassificationResult:
    intent:     str
    confidence: float       # in [0.0, 1.0]
    matched_terms: Tuple[str, ...] = ()  # for explainability + drift detection

    def is_actionable(self) -> bool:
        return self.intent in ACTIONABLE_INTENTS


# ── Keyword-bag rule table (P0 stub — replaced in P4) ────────────────────────
# Each entry: (lowercase phrase, intent). The first highest-score intent wins.
# Confidence = matched_terms_for_intent / total_distinct_terms_in_phrase_bag.
# Bound conservatively so that the stub never crosses production thresholds —
# operator review remains the safe default until P4 ships trained weights.

_RULES: List[Tuple[str, str]] = [
    # SAD / PZC arrival
    ("sad",                             INTENT_SAD_RECEIVED),
    ("pzc",                             INTENT_SAD_RECEIVED),
    ("zgloszenie celne",                INTENT_SAD_RECEIVED),  # PL: customs declaration
    ("clearance complete",              INTENT_SAD_RECEIVED),
    ("customs cleared",                 INTENT_SAD_RECEIVED),
    # Goods description
    ("hs code",                         INTENT_GOODS_DESCRIPTION),
    ("hs-code",                         INTENT_GOODS_DESCRIPTION),
    ("commodity code",                  INTENT_GOODS_DESCRIPTION),
    ("kod cn",                          INTENT_GOODS_DESCRIPTION),  # PL
    ("description of goods",            INTENT_GOODS_DESCRIPTION),
    ("commodity description",           INTENT_GOODS_DESCRIPTION),
    ("material composition",            INTENT_GOODS_DESCRIPTION),
    # Invoice
    ("invoice copy",                    INTENT_INVOICE),
    ("commercial invoice",              INTENT_INVOICE),
    ("faktura",                         INTENT_INVOICE),  # PL
    ("invoice value",                   INTENT_INVOICE),
    ("revised invoice",                 INTENT_INVOICE),
    # Authorization
    ("power of attorney",               INTENT_AUTHORIZATION),
    ("authorization letter",            INTENT_AUTHORIZATION),
    ("upoważnienie",                    INTENT_AUTHORIZATION),  # PL
    ("cesja",                           INTENT_AUTHORIZATION),  # PL: cession
    ("direct representation",           INTENT_AUTHORIZATION),
]

# Total distinct terms per intent (denominator for the confidence calc).
_TERMS_PER_INTENT: Dict[str, int] = {}
for _phrase, _intent in _RULES:
    _TERMS_PER_INTENT[_intent] = _TERMS_PER_INTENT.get(_intent, 0) + 1


# ── Public API ───────────────────────────────────────────────────────────────

def classify_clarification(body: str) -> ClassificationResult:
    """
    Classify a DHL clarification email body.

    Returns a ClassificationResult. Confidence is a *stub* signal in [0, 1]
    bounded conservatively. Callers that need to act on the result MUST
    consult the appropriate min_confidence threshold from settings.

    An empty / non-string body returns (unknown, 0.0).
    """
    if not isinstance(body, str) or not body.strip():
        return ClassificationResult(intent=INTENT_UNKNOWN, confidence=0.0)

    blob = body.lower()
    hits: Dict[str, List[str]] = {}
    for phrase, intent in _RULES:
        if phrase in blob:
            hits.setdefault(intent, []).append(phrase)

    if not hits:
        return ClassificationResult(intent=INTENT_UNKNOWN, confidence=0.0)

    # Score each intent by (distinct_matched_terms / total_terms_for_intent).
    # Cap the stub confidence at 0.80 so it never auto-crosses the P4/P5
    # thresholds (0.85 / 0.95). Production weights replace this in P4.
    best_intent = INTENT_UNKNOWN
    best_score  = 0.0
    best_terms: Tuple[str, ...] = ()
    for intent, matched in hits.items():
        denom = _TERMS_PER_INTENT.get(intent, 1) or 1
        score = min(0.80, len(set(matched)) / denom)
        if score > best_score:
            best_intent = intent
            best_score  = score
            best_terms  = tuple(sorted(set(matched)))

    return ClassificationResult(
        intent=best_intent,
        confidence=float(best_score),
        matched_terms=best_terms,
    )


def is_above_threshold(result: ClassificationResult, threshold: float) -> bool:
    """Convenience — True iff result is actionable AND confidence ≥ threshold."""
    if not result.is_actionable():
        return False
    return result.confidence >= float(threshold)
