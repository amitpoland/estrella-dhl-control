"""
dhl_clarification_validation_harness.py — Offline accuracy harness for the
DHL clarification classifier (P0 scaffold).

Reads a labelled corpus (CSV or JSONL), runs `classify_clarification()` on
each row, and emits an accuracy report (per-intent precision, recall,
confusion matrix, drift flags).

P0 commitment
=============
Corpus loading is NOT wired to production data. The operator (Tejal labels,
Amit spot-checks) points the harness at a corpus file when ready. Absent
corpus path → harness logs `corpus_not_provided` and exits with status 0
(no crash).

Expected corpus row shape
=========================
CSV columns:
    body,intent
JSONL keys per row:
    {"body": <str>, "intent": <one of CLASSIFIER_INTENTS>}

The harness is read-only. It never writes to the corpus file. It never calls
network or production state. Output is a structured dict the caller may
serialise or print.
"""
from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import dhl_clarification_classifier as classifier

log = logging.getLogger(__name__)


# ── Corpus loader ────────────────────────────────────────────────────────────

def load_corpus(path: Optional[Path]) -> List[Dict[str, str]]:
    """
    Load labelled examples from *path* (CSV or JSONL). Returns [] if path is
    None or does not exist. Never raises on missing file.
    """
    if path is None:
        log.info("corpus_not_provided")
        return []
    p = Path(path)
    if not p.exists():
        log.info("corpus_not_provided path=%s", p)
        return []
    suffix = p.suffix.lower()
    rows: List[Dict[str, str]] = []
    if suffix == ".jsonl":
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                body   = rec.get("body", "")
                intent = rec.get("intent", "")
                if body and intent:
                    rows.append({"body": str(body), "intent": str(intent)})
    elif suffix == ".csv":
        with p.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for rec in reader:
                body   = (rec.get("body") or "").strip()
                intent = (rec.get("intent") or "").strip()
                if body and intent:
                    rows.append({"body": body, "intent": intent})
    else:
        log.warning("unsupported_corpus_suffix path=%s suffix=%s", p, suffix)
    return rows


# ── Metrics ──────────────────────────────────────────────────────────────────

def _zero_per_intent_counts() -> Dict[str, Dict[str, int]]:
    return {
        intent: {"tp": 0, "fp": 0, "fn": 0}
        for intent in classifier.INTENTS
    }


def evaluate(
    corpus: Iterable[Dict[str, str]],
    *,
    p4_threshold: float = 0.85,
    p5_threshold: float = 0.95,
) -> Dict[str, Any]:
    """
    Run the classifier across *corpus*. Returns a structured report dict.

    Report shape:
        {
            "total_examples":      <int>,
            "overall_accuracy":    <float>,
            "per_intent": {
                <intent>: {"precision": <float>, "recall": <float>, "support": <int>},
                ...
            },
            "confusion_matrix": {
                <true_intent>: { <predicted_intent>: <count>, ... },
                ...
            },
            "above_p4_threshold_actionable": <int>,
            "above_p5_threshold_actionable": <int>,
            "drift_flags": [<str>, ...],
        }
    """
    counts = _zero_per_intent_counts()
    support: Dict[str, int] = defaultdict(int)
    confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    above_p4 = 0
    above_p5 = 0
    correct = 0
    total = 0

    for row in corpus:
        true_intent = row.get("intent") or ""
        body        = row.get("body") or ""
        if not true_intent or true_intent not in classifier.INTENTS:
            continue
        total += 1
        support[true_intent] += 1

        result = classifier.classify_clarification(body)
        pred = result.intent
        confusion[true_intent][pred] += 1

        if pred == true_intent:
            correct += 1
            counts[pred]["tp"] += 1
        else:
            counts[pred]["fp"] += 1
            counts[true_intent]["fn"] += 1

        if classifier.is_above_threshold(result, p4_threshold):
            above_p4 += 1
        if classifier.is_above_threshold(result, p5_threshold):
            above_p5 += 1

    per_intent_report: Dict[str, Dict[str, float]] = {}
    for intent, c in counts.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall    = tp / (tp + fn) if (tp + fn) else 0.0
        per_intent_report[intent] = {
            "precision": round(precision, 4),
            "recall":    round(recall, 4),
            "support":   support.get(intent, 0),
        }

    overall_accuracy = (correct / total) if total else 0.0

    drift_flags: List[str] = []
    # Per master-plan §4.5 R2: invoice ↔ goods_description confusion is the
    # most dangerous misclassification. Flag any non-zero off-diagonal between
    # them.
    if confusion.get("invoice", {}).get("goods_description"):
        drift_flags.append("invoice_classified_as_goods_description")
    if confusion.get("goods_description", {}).get("invoice"):
        drift_flags.append("goods_description_classified_as_invoice")
    # Any sad_received misclassification is high-severity — P5 triggers PZ.
    sad_misses = sum(
        v for k, v in confusion.get("sad_received", {}).items() if k != "sad_received"
    )
    if sad_misses:
        drift_flags.append(f"sad_received_misclassified_x{sad_misses}")

    return {
        "total_examples":               total,
        "overall_accuracy":             round(overall_accuracy, 4),
        "per_intent":                   per_intent_report,
        "confusion_matrix":             {k: dict(v) for k, v in confusion.items()},
        "above_p4_threshold_actionable": above_p4,
        "above_p5_threshold_actionable": above_p5,
        "drift_flags":                  drift_flags,
    }


# ── CLI entrypoint (callable from operator workflow) ─────────────────────────

def run(corpus_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Top-level harness entrypoint. Returns the report dict.

    On missing / unspecified corpus: logs `corpus_not_provided` and returns
    a zero-shaped report (graceful, no exception).
    """
    p = Path(corpus_path) if corpus_path else None
    rows = load_corpus(p)
    return evaluate(rows)
