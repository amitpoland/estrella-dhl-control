"""compliance_resolver.py — derive compliance intelligence from audit fields.

Secondary read-only authority for compliance badge states.  Consumed ONLY when
``compliance_intelligence_resolver_enabled`` is True in settings (default: False).

States
------
engine_verified        audit.verification[field] is True  (deterministic engine pass)
intelligence_resolved  field is None AND high-confidence contextual evidence found
gap                    field is None AND evidence absent or confidence too low
failed                 audit.verification[field] is False (deterministic engine fail)

The resolver NEVER mutates audit.json or audit.verification.  It produces a
``compliance_resolution`` object that routes_dashboard injects at read-time.

Intelligence is sourced exclusively from already-parsed fields inside the audit
dict (customs_declaration, verification, zc429, awb_fields).  No external calls,
no AI, no I/O.

Confidence levels
-----------------
deterministic  Direct engine verdict from audit.verification.
high           Two independent name sources extracted; Jaccard token overlap ≥ 0.4.
medium         Single source present only; no second source to compare against.
weak           Both sources present but overlap is 0.10–0.39.
none           No relevant evidence found.
"""
from __future__ import annotations

import re
from typing import Optional

# ── Token matching ─────────────────────────────────────────────────────────────

# Legal-form suffixes and stop-words that add noise to entity comparison.
_NOISE_TOKENS: frozenset[str] = frozenset({
    "ltd", "pvt", "llc", "inc", "gmbh", "sp", "z", "o", "s", "oo", "sa", "co",
    "corp", "limited", "private", "public", "the", "and", "of", "for",
})

_HIGH_THRESHOLD:   float = 0.40
_MEDIUM_THRESHOLD: float = 0.10

_COMPLIANCE_FIELDS = ("importer_match", "exporter_match", "qty_match_by_type", "vat_match")


def _tokenize(name: Optional[str]) -> frozenset[str]:
    """Return a frozenset of lower-case alpha tokens after stripping punctuation."""
    if not name:
        return frozenset()
    tokens = {
        t.strip(".,()/-") for t in re.split(r"[\s/]+", name.lower())
        if len(t.strip(".,()/-")) > 1
    }
    return frozenset(tokens - _NOISE_TOKENS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _name_state(
    sad_name: Optional[str],
    inv_name: Optional[str],
    field: str,
) -> dict:
    """Derive a per-field resolution result from two name strings."""
    if not sad_name and not inv_name:
        return {
            "state":      "gap",
            "confidence": "none",
            "evidence":   None,
            "source":     None,
        }
    if sad_name and not inv_name:
        return {
            "state":      "gap",
            "confidence": "medium",
            "evidence":   f"SAD name extracted ({sad_name!r}); no invoice name available to compare.",
            "source":     "sad_only",
        }
    if not sad_name and inv_name:
        return {
            "state":      "gap",
            "confidence": "medium",
            "evidence":   f"Invoice name extracted ({inv_name!r}); no SAD name available to compare.",
            "source":     "invoice_only",
        }
    # Both present — compute overlap.
    score = _jaccard(_tokenize(sad_name), _tokenize(inv_name))
    if score >= _HIGH_THRESHOLD:
        return {
            "state":      "intelligence_resolved",
            "confidence": "high",
            "evidence": (
                f"SAD {field.replace('_match','')} {sad_name!r} and invoice name "
                f"{inv_name!r} share sufficient token overlap ({score:.2f})."
            ),
            "source":     "sad+invoice",
        }
    if score >= _MEDIUM_THRESHOLD:
        return {
            "state":      "gap",
            "confidence": "weak",
            "evidence": (
                f"SAD name {sad_name!r} and invoice name {inv_name!r} have "
                f"low overlap ({score:.2f}); manual review recommended."
            ),
            "source":     "sad+invoice",
        }
    return {
        "state":      "gap",
        "confidence": "weak",
        "evidence": (
            f"SAD name {sad_name!r} and invoice name {inv_name!r} have "
            f"insufficient overlap ({score:.2f})."
        ),
        "source":     "sad+invoice",
    }


# ── Per-field resolvers ───────────────────────────────────────────────────────

def _resolve_importer(audit: dict) -> dict:
    cd       = audit.get("customs_declaration") or {}
    ver      = audit.get("verification") or {}
    zc429    = audit.get("zc429") or {}
    awb      = audit.get("awb_fields") or {}

    sad_name = cd.get("importer_name") or None
    inv_name = (
        ver.get("invoice_importer_name")
        or zc429.get("consignee")
        or awb.get("receiver_name")
        or None
    )
    return _name_state(sad_name, inv_name, "importer_match")


def _resolve_exporter(audit: dict) -> dict:
    cd    = audit.get("customs_declaration") or {}
    ver   = audit.get("verification") or {}
    zc429 = audit.get("zc429") or {}
    awb   = audit.get("awb_fields") or {}

    sad_name = cd.get("exporter_name") or None
    inv_name = (
        ver.get("invoice_exporter_name")
        or zc429.get("exporter_name")
        or zc429.get("exporter")
        or awb.get("shipper_name")
        or None
    )
    return _name_state(sad_name, inv_name, "exporter_match")


def _resolve_qty(audit: dict) -> dict:
    """qty_match_by_type requires per-category quantity comparison.

    Without structured category breakdowns from both invoice and SAD sides,
    no reliable intelligence resolution is possible.  Always returns gap.
    """
    cd    = audit.get("customs_declaration") or {}
    zc429 = audit.get("zc429") or {}

    has_sad_qty = bool(cd.get("total_pieces") or zc429.get("total_net_weight"))
    return {
        "state":      "gap",
        "confidence": "weak" if has_sad_qty else "none",
        "evidence": (
            "SAD quantity data present but per-type breakdown unavailable for comparison."
            if has_sad_qty else None
        ),
        "source": "sad_qty_only" if has_sad_qty else None,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_compliance(audit: dict) -> dict:
    """Derive compliance_resolution from a loaded audit dict.

    Pure function — no I/O, no side effects.  Never mutates ``audit``.

    Returns a dict keyed by compliance field name.  Each value has keys:
      state        engine_verified | intelligence_resolved | gap | failed
      confidence   deterministic | high | medium | weak | none
      evidence     human-readable string or None
      source       evidence source identifier or None

    Callers must wrap in try/except — any failure should be non-fatal.
    """
    ver = audit.get("verification") or {}
    out: dict = {}

    for field in _COMPLIANCE_FIELDS:
        v = ver.get(field)

        if v is True:
            out[field] = {
                "state":      "engine_verified",
                "confidence": "deterministic",
                "evidence":   None,
                "source":     "verification",
            }
        elif v is False:
            out[field] = {
                "state":      "failed",
                "confidence": "deterministic",
                "evidence":   None,
                "source":     "verification",
            }
        elif field == "importer_match":
            out[field] = _resolve_importer(audit)
        elif field == "exporter_match":
            out[field] = _resolve_exporter(audit)
        elif field == "qty_match_by_type":
            out[field] = _resolve_qty(audit)
        else:
            out[field] = {
                "state":      "gap",
                "confidence": "none",
                "evidence":   None,
                "source":     None,
            }

    return out
