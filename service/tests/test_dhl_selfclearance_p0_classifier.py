"""
test_dhl_selfclearance_p0_classifier.py — 4-intent classifier stub.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_clarification_classifier as cls  # noqa: E402


def test_four_actionable_intents_plus_unknown():
    assert cls.INTENT_GOODS_DESCRIPTION in cls.INTENTS
    assert cls.INTENT_INVOICE in cls.INTENTS
    assert cls.INTENT_AUTHORIZATION in cls.INTENTS
    assert cls.INTENT_SAD_RECEIVED in cls.INTENTS
    assert cls.INTENT_UNKNOWN in cls.INTENTS
    assert len(cls.INTENTS) == 5


def test_actionable_intents_excludes_unknown():
    assert cls.INTENT_UNKNOWN not in cls.ACTIONABLE_INTENTS
    assert len(cls.ACTIONABLE_INTENTS) == 4


def test_empty_body_returns_unknown_zero_conf():
    r = cls.classify_clarification("")
    assert r.intent == cls.INTENT_UNKNOWN
    assert r.confidence == 0.0


def test_non_string_body_returns_unknown():
    r = cls.classify_clarification(None)  # type: ignore[arg-type]
    assert r.intent == cls.INTENT_UNKNOWN


def test_goods_description_keywords_classify():
    r = cls.classify_clarification("Please provide the HS code for this shipment.")
    assert r.intent == cls.INTENT_GOODS_DESCRIPTION
    assert r.confidence > 0


def test_invoice_keywords_classify():
    r = cls.classify_clarification("Send the commercial invoice copy.")
    assert r.intent == cls.INTENT_INVOICE


def test_authorization_keywords_classify():
    r = cls.classify_clarification("Need power of attorney for direct representation.")
    assert r.intent == cls.INTENT_AUTHORIZATION


def test_sad_received_classifies():
    r = cls.classify_clarification("Please find attached the SAD / zgloszenie celne.")
    assert r.intent == cls.INTENT_SAD_RECEIVED


def test_no_match_returns_unknown():
    r = cls.classify_clarification("Hello, weather looks fine today.")
    assert r.intent == cls.INTENT_UNKNOWN


def test_stub_confidence_capped_below_p4_threshold():
    # Per scaffold contract, the P0 stub must NEVER auto-cross production thresholds.
    r = cls.classify_clarification("HS code commodity code material composition")
    assert r.confidence <= 0.80


def test_is_above_threshold_false_for_unknown():
    r = cls.ClassificationResult(intent=cls.INTENT_UNKNOWN, confidence=0.99)
    assert cls.is_above_threshold(r, threshold=0.5) is False


def test_is_above_threshold_true_for_actionable_above_thresh():
    r = cls.ClassificationResult(intent=cls.INTENT_INVOICE, confidence=0.9)
    assert cls.is_above_threshold(r, threshold=0.85) is True


def test_is_above_threshold_false_for_actionable_below_thresh():
    r = cls.ClassificationResult(intent=cls.INTENT_INVOICE, confidence=0.7)
    assert cls.is_above_threshold(r, threshold=0.85) is False


def test_matched_terms_populated():
    r = cls.classify_clarification("Please send the commercial invoice.")
    assert "commercial invoice" in r.matched_terms or "invoice copy" in r.matched_terms \
        or len(r.matched_terms) > 0
