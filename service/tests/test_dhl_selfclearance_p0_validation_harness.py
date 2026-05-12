"""
test_dhl_selfclearance_p0_validation_harness.py — corpus accuracy harness.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services import dhl_clarification_validation_harness as harness  # noqa: E402


def test_absent_corpus_returns_empty_report(tmp_path):
    report = harness.run(corpus_path=str(tmp_path / "missing.jsonl"))
    assert report["total_examples"] == 0
    assert report["overall_accuracy"] == 0.0
    assert report["drift_flags"] == []


def test_none_corpus_returns_empty_report():
    assert harness.run(corpus_path=None)["total_examples"] == 0


def test_jsonl_corpus_loads(tmp_path):
    p = tmp_path / "corpus.jsonl"
    rows = [
        {"body": "Please provide HS code", "intent": "goods_description"},
        {"body": "Send the commercial invoice", "intent": "invoice"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = harness.load_corpus(p)
    assert len(out) == 2


def test_csv_corpus_loads(tmp_path):
    p = tmp_path / "corpus.csv"
    p.write_text(
        "body,intent\n"
        "Please provide HS code,goods_description\n"
        "Send commercial invoice,invoice\n",
        encoding="utf-8",
    )
    out = harness.load_corpus(p)
    assert len(out) == 2
    assert out[0]["intent"] == "goods_description"


def test_evaluate_yields_per_intent_metrics(tmp_path):
    corpus = [
        {"body": "Please provide HS code commodity description", "intent": "goods_description"},
        {"body": "Need the commercial invoice copy", "intent": "invoice"},
        {"body": "Send power of attorney", "intent": "authorization"},
        {"body": "Attached is the SAD / zgloszenie celne", "intent": "sad_received"},
    ]
    report = harness.evaluate(corpus)
    assert report["total_examples"] == 4
    assert "goods_description" in report["per_intent"]
    assert "invoice" in report["per_intent"]
    # All four canonical intents present in the per-intent dict.
    for intent in ("goods_description", "invoice", "authorization", "sad_received"):
        assert intent in report["per_intent"]


def test_evaluate_invoice_goods_confusion_drift_flag():
    # Build a misclassification scenario: invoice body that the stub classifies
    # as goods_description because the goods_description keyword set fires.
    corpus = [
        {"body": "HS code commodity description please", "intent": "invoice"},
    ]
    report = harness.evaluate(corpus)
    # Confusion matrix should record this off-diagonal cell AND the drift
    # flag must be emitted (the most dangerous misclassification per R2).
    assert "drift_flags" in report
    assert len(report["drift_flags"]) > 0
    assert "invoice_classified_as_goods_description" in report["drift_flags"]
