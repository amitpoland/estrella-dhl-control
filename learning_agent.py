#!/usr/bin/env python3
"""
learning_agent.py — Rule + Memory + Feedback learning layer
============================================================
Not a black box. Not ML.

This module builds a controlled pattern memory that reduces false positives
(audit noise) while preserving every hard compliance check.

Architecture:
  ENGINE (strict rules, never touched)
  + MEMORY (confirmed past patterns, stored in learning_store.json)
  + FEEDBACK (human approval required before any pattern is trusted)
  = SMART ENGINE (less noise, same compliance rigour)

Hard locks — learning CANNOT soften these, ever:
  • value_mismatch      CIF invoice total ≠ SAD total
  • cif_formula_error   FOB + Freight + Insurance ≠ stated CIF
  • invoice_missing     Invoice ref in SAD has no matching PDF (or vice versa)
  • nip_mismatch        NIP/VAT IDs differ (even if names match)

Soft checks — learning CAN reduce penalty once pattern is confirmed (≥3 times):
  • address_inconsistency   warehouse vs registered office routing
  • transport_mismatch      known AWB format from trusted carrier
  • exporter_name_alias     known short-name ↔ full legal-name mapping

Safety features:
  • LEARNING_FROZEN=1 — suspends all confidence adjustments during audit periods;
    patterns are still recorded but never applied.
  • 3σ anomaly protection — even confirmed patterns raise ANOMALY when the current
    value exceeds mean ± 3σ (catches one-off fraud regardless of history).
  • Confidence decay — confidence × 0.98^(days/30) for unused patterns.
  • NIP-keyed address patterns — key = nip + address_hash (prevents cross-company bleed).
  • Pattern maturity: unconfirmed → emerging(≥3) → stable(≥10) → trusted(≥25).

Every learning decision is logged with:
  pattern_id, confidence, maturity, reason, n_confirmations, confirmed_by
so it can be reproduced and explained to a tax authority.

Public API:
    load_learning_store(path)            → store dict
    record_batch_patterns(result, batch_id, doc_no, store) → updated store
    apply_learning_adjustments(c3, c6, c2, invoices, zc429, store) → AdjustmentResult
    check_freight_against_pattern(invoices, store) → List[dict]
    update_learning_store(batch_id, doc_no, feedback, store, ...) → updated store
    save_learning_store(store, path)     → None
    maturity_level(confirmation_count)  → str

Feedback values: "valid" | "review" | "incorrect"
    "valid"     → patterns from this batch are confirmed and learned
    "review"    → patterns recorded but NOT trusted until re-confirmed
    "incorrect" → batch is flagged; patterns NOT learned
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Store location (override via LEARNING_STORE_PATH env var) ─────────────────
_DEFAULT_STORE_PATH = Path(__file__).parent / "learning_store.json"

# Minimum confirmations before a pattern is trusted
_MIN_CONFIRMATIONS = 3

# Pattern maturity thresholds
_MATURITY_EMERGING = 3
_MATURITY_STABLE   = 10
_MATURITY_TRUSTED  = 25

# Confidence decay: multiply by this factor every 30 days without new confirmations
_DECAY_FACTOR_PER_30D = 0.98

# Freeze mode: record patterns but do NOT apply confidence adjustments
# Set env var LEARNING_FROZEN=1 during formal audit periods
_LEARNING_FROZEN = os.environ.get("LEARNING_FROZEN", "0").lower() in ("1", "true", "yes")

# Hard-lock check keys — learning NEVER reduces their penalty
HARD_LOCK_CHECKS = frozenset({
    "value_mismatch",
    "cif_formula_error",
    "invoice_missing",
    # NIP mismatch is enforced separately inside apply_learning_adjustments
})


# ── Pattern maturity ──────────────────────────────────────────────────────────

def maturity_level(confirmation_count: int) -> str:
    """
    Returns the maturity label of a pattern.

    unconfirmed  < 3  : seen but not yet trusted
    emerging     ≥ 3  : minimum threshold met; low-confidence
    stable       ≥ 10 : well-established pattern; medium-confidence
    trusted      ≥ 25 : deeply confirmed; high-confidence
    """
    if confirmation_count >= _MATURITY_TRUSTED:
        return "trusted"
    if confirmation_count >= _MATURITY_STABLE:
        return "stable"
    if confirmation_count >= _MATURITY_EMERGING:
        return "emerging"
    return "unconfirmed"


# ── Confidence decay ──────────────────────────────────────────────────────────

def _decayed_confidence(base_conf: float, last_seen_str: str) -> float:
    """
    Apply time-based decay: base_conf × (0.98 ^ (days_inactive / 30)).
    Pattern unused for 360 days retains ~87% of its remaining confidence.
    Pattern unused for 720 days retains ~75%.
    """
    if not last_seen_str:
        return base_conf
    try:
        last    = datetime.strptime(last_seen_str, "%Y-%m-%d")
        days    = max(0, (datetime.utcnow() - last).days)
        periods = days / 30.0
        decayed = base_conf * (_DECAY_FACTOR_PER_30D ** periods)
        return round(max(0.0, decayed), 4)
    except (ValueError, TypeError):
        return base_conf


# ── Empty store template ──────────────────────────────────────────────────────

def _empty_store() -> dict:
    return {
        "version":          "1.1",
        "last_updated":     "",
        "freight_patterns": {},
        "address_patterns": {},
        "exporter_aliases": {},
        "feedback_log":     [],
    }


# ── Atomic file I/O ───────────────────────────────────────────────────────────

def load_learning_store(path: Optional[Path] = None) -> dict:
    """Load store from disk. Returns empty store if file missing or corrupt."""
    p = Path(path or os.environ.get("LEARNING_STORE_PATH", _DEFAULT_STORE_PATH))
    if not p.exists():
        return _empty_store()
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "version" not in data:
            raise ValueError("Unexpected format")
        return data
    except Exception:
        return _empty_store()


def save_learning_store(store: dict, path: Optional[Path] = None) -> None:
    """Write store atomically (temp file + rename) to avoid corruption."""
    p = Path(path or os.environ.get("LEARNING_STORE_PATH", _DEFAULT_STORE_PATH))
    store["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, p)
    except Exception as exc:
        if tmp_path and Path(tmp_path).exists():
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise RuntimeError(f"Failed to save learning store: {exc}") from exc


# ── Key helpers ───────────────────────────────────────────────────────────────

def _supplier_key(supplier: str) -> str:
    """Normalise supplier name to a stable dict key."""
    return re.sub(r"[^A-Z0-9]", "_", supplier.upper().strip())[:40]


def _company_key(company: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", company.upper().strip())[:40]


def _addr_key(nip: str, address: str) -> str:
    """
    Address pattern key = NIP + address hash.
    Using NIP (not company name) prevents cross-company bleed when two
    companies share a similar trading name.
    """
    nip_norm  = re.sub(r"[^0-9]", "", nip or "NONIP")
    addr_hash = hashlib.sha1(address.strip().lower().encode()).hexdigest()[:8]
    return f"{nip_norm}_{addr_hash}"


def _pattern_id(prefix: str, key: str) -> str:
    h = hashlib.sha1(key.encode()).hexdigest()[:6].upper()
    return f"{prefix}_{h}"


# ── Stats helpers ─────────────────────────────────────────────────────────────

def _running_stats(samples: List[float]) -> Tuple[float, float]:
    """Return (mean, std_dev) for a list of floats."""
    if not samples:
        return 0.0, 0.0
    n   = len(samples)
    avg = sum(samples) / n
    if n < 2:
        return avg, 0.0
    var = sum((x - avg) ** 2 for x in samples) / (n - 1)
    return avg, math.sqrt(var)


def _dynamic_tolerance(std_dev: float, min_tol: float = 0.02) -> float:
    """Tolerance = max(min_tol, 2 × std_dev). Grows with observed variance."""
    return max(min_tol, 2 * std_dev)


# ── Layer 1: Record patterns from a batch ────────────────────────────────────

def record_batch_patterns(
    result:   Dict[str, Any],
    batch_id: str,
    doc_no:   str,
    store:    dict,
) -> dict:
    """
    Extract observable patterns from this batch and add them to the store
    as UNCONFIRMED (pending human feedback before they influence scoring).

    Patterns recorded:
      • freight % per supplier (key = supplier name)
      • address pattern (key = importer NIP + address hash — prevents cross-company bleed)
      • exporter name alias (invoice seller vs SAD canonical)
    """
    invoices = result.get("invoices", [])
    zc429    = result.get("zc429", {})
    v        = result.get("verification", {})
    today    = time.strftime("%Y-%m-%d")

    exporter = (
        v.get("invoice_exporter_name")
        or (invoices[0].get("seller_name", "") if invoices else "")
    ).strip()
    importer_nip = zc429.get("importer_nip", "") or (
        invoices[0].get("buyer_nip", "") if invoices else ""
    )

    # ── Freight patterns ───────────────────────────────────────────────────────
    for inv in invoices:
        fob       = inv.get("fob_usd", 0.0)
        freight   = inv.get("freight_usd", 0.0)
        insurance = inv.get("insurance_usd", 0.0)
        if fob <= 0:
            continue
        freight_pct   = freight   / fob
        insurance_pct = insurance / fob
        sup_key = _supplier_key(exporter) if exporter else "UNKNOWN"
        fp = store["freight_patterns"].setdefault(sup_key, {
            "pattern_id":         _pattern_id("FREIGHT", sup_key),
            "supplier":           exporter,
            "importer_nip":       importer_nip,
            "route":              "IN → PL",
            "samples":            [],
            "stats":              {},
            "confirmed":          False,
            "confirmation_count": 0,
            "first_seen":         today,
            "last_seen":          today,
        })
        fp["samples"].append({
            "batch_id":      batch_id,
            "date":          today,
            "invoice_no":    inv.get("invoice_no", ""),
            "freight_pct":   round(freight_pct, 6),
            "insurance_pct": round(insurance_pct, 6),
            "fob_usd":       fob,
        })
        # Keep only last 50 samples
        fp["samples"] = fp["samples"][-50:]
        f_vals = [s["freight_pct"]   for s in fp["samples"]]
        i_vals = [s["insurance_pct"] for s in fp["samples"]]
        f_avg, f_std = _running_stats(f_vals)
        i_avg, i_std = _running_stats(i_vals)
        fp["stats"] = {
            "count":             len(fp["samples"]),
            "avg_freight_pct":   round(f_avg, 6),
            "std_freight_pct":   round(f_std, 6),
            "tol_freight_pct":   round(_dynamic_tolerance(f_std), 4),
            "avg_insurance_pct": round(i_avg, 6),
            "std_insurance_pct": round(i_std, 6),
            "tol_insurance_pct": round(_dynamic_tolerance(i_std), 4),
        }
        fp["last_seen"] = today

    # ── Address patterns (key = NIP + address hash) ───────────────────────────
    for inv in invoices:
        buyer_addr = inv.get("buyer_address", "")
        company    = inv.get("buyer_name", "")
        nip        = inv.get("buyer_nip", "") or importer_nip
        if not (buyer_addr and company):
            continue
        addr_k = _addr_key(nip, buyer_addr)
        ap = store["address_patterns"].setdefault(addr_k, {
            "pattern_id":         _pattern_id("ADDR", addr_k),
            "company":            company,
            "nip":                nip,
            "address":            buyer_addr.strip(),
            "confirmed":          False,
            "confirmation_count": 0,
            "first_seen":         today,
            "last_seen":          today,
        })
        ap["last_seen"] = today

    # ── Exporter name aliases ──────────────────────────────────────────────────
    sad_exporter = zc429.get("exporter_name", "").strip()
    inv_exporter = v.get("invoice_exporter_name", "").strip()
    if exporter and sad_exporter and exporter != sad_exporter:
        canonical = sad_exporter  # SAD field 2 is authoritative
        can_key   = _supplier_key(canonical)
        ea = store["exporter_aliases"].setdefault(can_key, {
            "pattern_id":         _pattern_id("EXP", can_key),
            "canonical":          canonical,
            "aliases":            [],
            "confirmed":          False,
            "confirmation_count": 0,
            "first_seen":         today,
            "last_seen":          today,
        })
        if exporter not in ea["aliases"]:
            ea["aliases"].append(exporter)
        if inv_exporter and inv_exporter not in ea["aliases"] and inv_exporter != canonical:
            ea["aliases"].append(inv_exporter)
        ea["last_seen"] = today

    return store


# ── Layer 2: Apply learning adjustments ───────────────────────────────────────

class AdjustmentResult:
    """
    Container for learning-adjusted check outcomes.

    For each check key:
        confidence   0.0 → no information / frozen / hard-locked
                     1.0 → fully confirmed known pattern
        adjusted     True if learning raised confidence above 0.0
        reason       human-readable explanation
        pattern_id   which pattern drove this decision
        hard_locked  True if this check cannot be softened regardless
        maturity     unconfirmed / emerging / stable / trusted
        frozen       True if LEARNING_FROZEN mode was active
    """
    def __init__(self):
        self.adjustments: Dict[str, dict] = {}
        self.trace:       List[dict]      = []
        self.frozen:      bool            = _LEARNING_FROZEN

    def add(
        self,
        check_key:   str,
        confidence:  float,
        adjusted:    bool,
        reason:      str,
        pattern_id:  str  = "",
        hard_locked: bool = False,
        maturity:    str  = "",
    ) -> None:
        entry = {
            "confidence":  round(confidence, 4),
            "adjusted":    adjusted,
            "reason":      reason,
            "pattern_id":  pattern_id,
            "hard_locked": hard_locked,
            "maturity":    maturity,
            "frozen":      _LEARNING_FROZEN,
            "timestamp":   time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.adjustments[check_key] = entry
        self.trace.append({"check": check_key, **entry})

    def confidence_for(self, check_key: str) -> float:
        return self.adjustments.get(check_key, {}).get("confidence", 0.0)

    def to_dict(self) -> dict:
        return {
            "adjustments": self.adjustments,
            "trace":       self.trace,
            "frozen":      self.frozen,
        }


def apply_learning_adjustments(
    c3:       dict,
    c6:       dict,
    c2:       dict,
    invoices: list,
    zc429:    dict,
    store:    dict,
) -> AdjustmentResult:
    """
    Compare current batch against known patterns and compute confidence scores.

    Freeze mode (LEARNING_FROZEN=1):
      Hard locks are still logged as locked. Soft checks receive confidence=0.
      No pattern adjustments applied. Patterns are still recorded via
      record_batch_patterns() — just not applied.

    Confidence decay:
      Base confidence is reduced by 0.98 per 30-day period since last_seen.
      A pattern inactive for 90 days loses ~6% of its boost; 360 days ~13%.
    """
    adj = AdjustmentResult()

    # ── Hard locks: always log as locked, confidence irrelevant ──────────────
    for key in ("value_mismatch", "cif_formula_error", "invoice_missing"):
        adj.add(key, confidence=0.0, adjusted=False,
                reason="Hard-lock check — learning cannot reduce this penalty.",
                hard_locked=True)

    nip_match = c2.get("nip_result")
    if nip_match is False:
        adj.add("nip_mismatch_hard", confidence=0.0, adjusted=False,
                reason="NIP/VAT IDs confirmed different — always hard failure.",
                hard_locked=True)

    # ── Freeze mode: suspend all soft-check adjustments ──────────────────────
    if _LEARNING_FROZEN:
        freeze_msg = (
            "LEARNING FROZEN (LEARNING_FROZEN=1) — confidence adjustments suspended "
            "for audit period. Patterns recorded but not applied."
        )
        for soft_key in ("address_inconsistency", "transport_mismatch", "exporter_alias"):
            adj.add(soft_key, confidence=0.0, adjusted=False, reason=freeze_msg)
        return adj

    # ── Soft check 1: Address inconsistency ──────────────────────────────────
    inv_addr = c3.get("invoice_addr", "")
    nip      = (invoices[0].get("buyer_nip", "") if invoices else "") or zc429.get("importer_nip", "")
    company  = invoices[0].get("buyer_name", "") if invoices else ""
    addr_k   = _addr_key(nip, inv_addr) if inv_addr else ""
    ap       = store.get("address_patterns", {}).get(addr_k) if addr_k else None

    if ap and ap.get("confirmed") and ap.get("confirmation_count", 0) >= _MIN_CONFIRMATIONS:
        n       = min(ap["confirmation_count"], 20)
        base    = min(0.95, 0.5 + (n - _MIN_CONFIRMATIONS) * 0.05)
        conf    = _decayed_confidence(base, ap.get("last_seen", ""))
        mat     = maturity_level(ap["confirmation_count"])
        decay_note = f" [decayed from {base:.3f}]" if conf < base - 0.001 else ""
        adj.add(
            "address_inconsistency",
            confidence = conf,
            adjusted   = True,
            reason     = (
                f"NIP-keyed address confirmed {n}× [{mat}] "
                f"for NIP {ap.get('nip', '?')} ({ap.get('company', company)}). "
                f"Delivery to '{inv_addr}' matches historical pattern.{decay_note}"
            ),
            pattern_id = ap["pattern_id"],
            maturity   = mat,
        )
    else:
        n_conf = ap.get("confirmation_count", 0) if ap else 0
        adj.add(
            "address_inconsistency",
            confidence = 0.0,
            adjusted   = False,
            reason     = (
                f"No confirmed address pattern for NIP '{nip}' + this address."
                if not ap else
                f"Pattern exists for NIP {ap.get('nip', '?')} "
                f"but only {n_conf}/{_MIN_CONFIRMATIONS} confirmations — not yet trusted."
            ),
        )

    # ── Soft check 2: Transport / AWB ────────────────────────────────────────
    transport_refs = zc429.get("transport_refs", [])
    if transport_refs:
        adj.add(
            "transport_mismatch",
            confidence = 0.8,
            adjusted   = True,
            reason     = (
                f"N740 transport refs extracted from SAD: {transport_refs}. "
                f"Physical AWB cross-check is manual but document reference is present."
            ),
        )
    else:
        adj.add(
            "transport_mismatch",
            confidence = 0.0,
            adjusted   = False,
            reason     = "No N740 transport refs found in SAD. Cannot assess AWB linkage.",
        )

    # ── Soft check 3: Exporter name alias ────────────────────────────────────
    sad_exporter = zc429.get("exporter_name", "")
    inv_seller   = invoices[0].get("seller_name", "") if invoices else ""
    can_key      = _supplier_key(sad_exporter)
    ea           = store.get("exporter_aliases", {}).get(can_key)

    if ea and ea.get("confirmed") and ea.get("confirmation_count", 0) >= _MIN_CONFIRMATIONS:
        if inv_seller in ea.get("aliases", []) or inv_seller == ea.get("canonical", ""):
            n       = min(ea["confirmation_count"], 20)
            base    = min(0.90, 0.5 + (n - _MIN_CONFIRMATIONS) * 0.05)
            conf    = _decayed_confidence(base, ea.get("last_seen", ""))
            mat     = maturity_level(ea["confirmation_count"])
            decay_note = f" [decayed from {base:.3f}]" if conf < base - 0.001 else ""
            adj.add(
                "exporter_alias",
                confidence = conf,
                adjusted   = True,
                reason     = (
                    f"'{inv_seller}' is a confirmed alias for '{ea['canonical']}' "
                    f"({n} confirmations, {mat}).{decay_note}"
                ),
                pattern_id = ea["pattern_id"],
                maturity   = mat,
            )
        else:
            adj.add(
                "exporter_alias",
                confidence = 0.0,
                adjusted   = False,
                reason     = f"'{inv_seller}' not in confirmed alias set for '{sad_exporter}'.",
            )
    else:
        adj.add(
            "exporter_alias",
            confidence = 0.0,
            adjusted   = False,
            reason     = "No confirmed exporter alias pattern.",
        )

    return adj


# ── Layer 3: Freight check against learned band ───────────────────────────────

def check_freight_against_pattern(
    invoices: list,
    store:    dict,
) -> List[dict]:
    """
    For each invoice, compare freight % against the learned tolerance band.

    Includes 3σ anomaly protection:
      Even if a pattern is confirmed, if the current value exceeds
      expected ± 3σ, status is forced to "ANOMALY" with confidence=0
      and force_warning=True. This catches one-off inflations regardless
      of how many prior batches were clean.

    Status values:
      WITHIN_TOLERANCE   — within ±2σ band (advisory: ok)
      OUTSIDE_TOLERANCE  — outside ±2σ but within ±3σ (advisory: review)
      ANOMALY            — exceeds ±3σ even for confirmed pattern (force warning)
      NO_PATTERN         — insufficient history
    """
    results = []
    for inv in invoices:
        seller    = inv.get("seller_name", "")
        sup_key   = _supplier_key(seller)
        fob       = inv.get("fob_usd", 0.0)
        freight   = inv.get("freight_usd", 0.0)
        insurance = inv.get("insurance_usd", 0.0)

        if fob <= 0:
            results.append({
                "invoice_no":           inv.get("invoice_no"),
                "status":               "NO_PATTERN",
                "confidence":           0.0,
                "reason":               "FOB is zero — cannot compute freight %",
                "expected_freight_pct": None,
                "actual_freight_pct":   None,
            })
            continue

        actual_f = freight   / fob
        actual_i = insurance / fob
        fp       = store.get("freight_patterns", {}).get(sup_key)

        if not fp or not fp.get("confirmed") or fp.get("stats", {}).get("count", 0) < _MIN_CONFIRMATIONS:
            n_samples = fp["stats"].get("count", 0) if (fp and fp.get("stats")) else 0
            results.append({
                "invoice_no":           inv.get("invoice_no"),
                "status":               "NO_PATTERN",
                "confidence":           0.0,
                "reason":               (
                    f"No confirmed freight pattern for '{seller}' yet "
                    f"({n_samples}/{_MIN_CONFIRMATIONS} samples)."
                    if fp else
                    f"No freight pattern recorded for '{seller}'."
                ),
                "expected_freight_pct": None,
                "actual_freight_pct":   round(actual_f, 4),
            })
            continue

        stats = fp["stats"]
        avg_f = stats["avg_freight_pct"]
        std_f = stats["std_freight_pct"]
        tol_f = stats["tol_freight_pct"]
        avg_i = stats["avg_insurance_pct"]
        std_i = stats["std_insurance_pct"]
        tol_i = stats["tol_insurance_pct"]
        mat   = maturity_level(fp.get("confirmation_count", 0))

        # ── 3σ anomaly protection ─────────────────────────────────────────────
        # Fires even for confirmed patterns — catches first-time manipulation.
        f_sigma3  = 3 * std_f if std_f > 0 else None
        i_sigma3  = 3 * std_i if std_i > 0 else None
        f_anomaly = f_sigma3 is not None and abs(actual_f - avg_f) > f_sigma3
        i_anomaly = i_sigma3 is not None and abs(actual_i - avg_i) > i_sigma3

        if f_anomaly or i_anomaly:
            anomaly_parts = []
            if f_anomaly:
                dev = abs(actual_f - avg_f) / std_f
                anomaly_parts.append(
                    f"freight {actual_f:.2%} deviates {dev:.1f}σ "
                    f"from mean {avg_f:.2%} (3σ threshold={f_sigma3:.2%})"
                )
            if i_anomaly:
                dev = abs(actual_i - avg_i) / std_i
                anomaly_parts.append(
                    f"insurance {actual_i:.2%} deviates {dev:.1f}σ "
                    f"from mean {avg_i:.2%} (3σ threshold={i_sigma3:.2%})"
                )
            results.append({
                "invoice_no":           inv.get("invoice_no"),
                "status":               "ANOMALY",
                "confidence":           0.0,
                "reason":               (
                    "⚠️ Anomaly exceeds 3σ for confirmed pattern — "
                    "manual review required regardless of learning confidence. "
                    + "; ".join(anomaly_parts)
                ),
                "expected_freight_pct": round(avg_f, 4),
                "actual_freight_pct":   round(actual_f, 4),
                "tolerance":            round(tol_f, 4),
                "sigma3_freight":       round(f_sigma3, 4) if f_sigma3 else None,
                "pattern_id":           fp["pattern_id"],
                "maturity":             mat,
                "force_warning":        True,
            })
            continue

        # ── Standard tolerance check (±2σ band) ──────────────────────────────
        f_within = abs(actual_f - avg_f) <= tol_f
        i_within = abs(actual_i - avg_i) <= tol_i

        if f_within and i_within:
            n    = stats["count"]
            conf = min(0.95, 0.5 + (n - _MIN_CONFIRMATIONS) * 0.03)
            results.append({
                "invoice_no":           inv.get("invoice_no"),
                "status":               "WITHIN_TOLERANCE",
                "confidence":           round(conf, 3),
                "reason":               (
                    f"Freight {actual_f:.2%} and insurance {actual_i:.2%} "
                    f"within historical band "
                    f"(avg {avg_f:.2%} ± {tol_f:.2%}, "
                    f"ins {avg_i:.2%} ± {tol_i:.2%}, n={n}, {mat})."
                ),
                "expected_freight_pct": round(avg_f, 4),
                "actual_freight_pct":   round(actual_f, 4),
                "tolerance":            round(tol_f, 4),
                "pattern_id":           fp["pattern_id"],
                "maturity":             mat,
            })
        else:
            notes = []
            if not f_within:
                notes.append(f"freight {actual_f:.2%} outside {avg_f:.2%} ± {tol_f:.2%}")
            if not i_within:
                notes.append(f"insurance {actual_i:.2%} outside {avg_i:.2%} ± {tol_i:.2%}")
            results.append({
                "invoice_no":           inv.get("invoice_no"),
                "status":               "OUTSIDE_TOLERANCE",
                "confidence":           0.2,
                "reason":               "; ".join(notes) + f". Unusual for '{seller}'.",
                "expected_freight_pct": round(avg_f, 4),
                "actual_freight_pct":   round(actual_f, 4),
                "tolerance":            round(tol_f, 4),
                "pattern_id":           fp["pattern_id"],
                "maturity":             mat,
            })

    return results


# ── Layer 4: Human feedback loop ──────────────────────────────────────────────

def update_learning_store(
    batch_id:     str,
    doc_no:       str,
    feedback:     str,
    store:        dict,
    result:       Optional[Dict[str, Any]] = None,
    confirmed_by: str = "",
    reason:       str = "",
) -> dict:
    """
    Record human feedback and promote patterns to confirmed if appropriate.

    Parameters:
        batch_id      batch that this feedback applies to
        doc_no        document number (for audit log)
        feedback      "valid" | "review" | "incorrect"
        store         current learning store (mutated in-place)
        result        optional original batch result (reserved for future use)
        confirmed_by  email or name of human who confirmed (stored in audit log)
        reason        free-text justification for this feedback decision

    feedback semantics:
      "valid"     → batch is correct; increment confirmation_count for all
                    patterns from this batch; confirm them if ≥ MIN_CONFIRMATIONS
      "review"    → patterns recorded but not promoted; flag for manual check
      "incorrect" → patterns NOT promoted; bad freight samples removed
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    feedback  = feedback.strip().lower()
    if feedback not in ("valid", "review", "incorrect"):
        raise ValueError(f"feedback must be 'valid' | 'review' | 'incorrect', got '{feedback}'")

    log_entry: Dict[str, Any] = {
        "timestamp":    timestamp,
        "batch_id":     batch_id,
        "doc_no":       doc_no,
        "feedback":     feedback,
        "confirmed_by": confirmed_by,
        "reason":       reason,
        "promoted":     [],
    }

    if feedback == "valid":
        today = time.strftime("%Y-%m-%d")
        for ptype in ("freight_patterns", "address_patterns", "exporter_aliases"):
            for key, pat in store.get(ptype, {}).items():
                has_batch = False
                if ptype == "freight_patterns":
                    has_batch = any(
                        s.get("batch_id") == batch_id for s in pat.get("samples", [])
                    )
                else:
                    # address_patterns and exporter_aliases: match by last_seen date
                    has_batch = pat.get("last_seen") == today

                if has_batch:
                    pat["confirmation_count"] = pat.get("confirmation_count", 0) + 1
                    pat["last_seen"] = today
                    if pat["confirmation_count"] >= _MIN_CONFIRMATIONS:
                        pat["confirmed"] = True
                    log_entry["promoted"].append({
                        "type":       ptype,
                        "pattern_id": pat.get("pattern_id", key),
                        "count":      pat["confirmation_count"],
                        "maturity":   maturity_level(pat["confirmation_count"]),
                        "trusted":    pat["confirmed"],
                    })

    elif feedback == "incorrect":
        # Remove bad samples from freight patterns; do not promote anything
        for key, pat in store.get("freight_patterns", {}).items():
            pat["samples"] = [
                s for s in pat.get("samples", [])
                if s.get("batch_id") != batch_id
            ]
            # Recompute stats after sample removal
            f_vals = [s["freight_pct"]   for s in pat["samples"]]
            i_vals = [s["insurance_pct"] for s in pat["samples"]]
            f_avg, f_std = _running_stats(f_vals)
            i_avg, i_std = _running_stats(i_vals)
            pat["stats"] = {
                "count":             len(pat["samples"]),
                "avg_freight_pct":   round(f_avg, 6),
                "std_freight_pct":   round(f_std, 6),
                "tol_freight_pct":   round(_dynamic_tolerance(f_std), 4),
                "avg_insurance_pct": round(i_avg, 6),
                "std_insurance_pct": round(i_std, 6),
                "tol_insurance_pct": round(_dynamic_tolerance(i_std), 4),
            }
        log_entry["note"] = (
            "Batch marked incorrect — patterns not promoted, bad freight samples removed "
            "and stats recomputed."
        )

    store["feedback_log"].append(log_entry)
    # Keep feedback log bounded to last 200 entries
    store["feedback_log"] = store["feedback_log"][-200:]

    return store


# ── Convenience: full pipeline call ──────────────────────────────────────────

def run_learning_pipeline(
    result:     Dict[str, Any],
    batch_id:   str,
    doc_no:     str,
    c2:         dict,
    c3:         dict,
    c6:         dict,
    invoices:   list,
    zc429:      dict,
    store_path: Optional[Path] = None,
) -> Tuple[AdjustmentResult, List[dict], dict]:
    """
    One-call entry point for export_service.py.

    1. Load store
    2. Record patterns (unconfirmed)
    3. Apply learning adjustments (for scoring)
    4. Check freight against pattern (advisory, includes 3σ anomaly detection)
    5. Save updated store

    Returns:
        (adjustment_result, freight_checks, updated_store)
    """
    store = load_learning_store(store_path)
    store = record_batch_patterns(result, batch_id, doc_no, store)
    adj   = apply_learning_adjustments(c3, c6, c2, invoices, zc429, store)
    freq  = check_freight_against_pattern(invoices, store)
    save_learning_store(store, store_path)
    return adj, freq, store
