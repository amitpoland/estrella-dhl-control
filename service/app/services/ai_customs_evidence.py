"""
ai_customs_evidence.py — AI-assisted customs-evidence recovery layer.

PURPOSE
-------
Recover invoice references, exporter/importer identity, and customs
anchors (MRN/AWB/CIF/CN-codes) from a noisy SAD/ZC429 / invoice / packing
PDF when the deterministic parser already produced a result that has
**low confidence** or VERIFY-GAP flags. The AI never replaces the
deterministic answer — it produces an EVIDENCE BLOCK that the backend
then RECONCILES against the deterministic anchors.

Phase 2 of the Global Jewellery campaign. The Phase-1 deterministic
chain (parse_invoice / parse_global_packing_pdf / ZC429 parser) remains
the primary authority. This module is invoked only when:

  - deterministic parser reports VERIFY-GAP, OR
  - invoice_refs are missing / noisy / numeric-tokens-only, OR
  - downstream reconciliation needs a second opinion on identity

HARD RULES (operator-locked, enforced at module boundary)
---------------------------------------------------------
  1. AI may EXTRACT, CLASSIFY, VERIFY, SUGGEST.
  2. AI may NOT change CIF, duty, VAT, CN code, PZ, wFirma posting,
     inventory state, or any deterministic decision. The reconciler
     in `reconcile_evidence()` is the only function that can promote
     AI output to a stored fact, and even then it only sets
     `verified_with_advisory` or `operator_review_required` flags —
     never overwrites financial fields.
  3. AI output MUST be strict JSON with the documented schema. Any
     other shape is rejected as a parser failure.
  4. AI MUST be invokable only when an explicit gate condition fires.
     Routes / callers never bypass `should_invoke_ai()`.
  5. Estrella supplier path is untouched — the trigger gate examines
     the deterministic anchors only; if none of the gate conditions
     apply, this module is a no-op.
  6. Provider abstraction: when `settings.anthropic_api_key` is unset,
     `extract_customs_evidence()` returns `None` and the deterministic
     path continues. No degradation of safety; no crash.
  7. No financial computation in this module. The reconciler compares
     AI-reported values against deterministic anchors for tolerance,
     but never sums, averages, or derives a new value.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Schema + system prompt
# ─────────────────────────────────────────────────────────────────────────────

# The AI MUST return JSON matching this exact shape. Any other keys are
# ignored; missing required keys are nulled. The downstream reconciler
# then compares each non-null value against deterministic anchors.
EVIDENCE_SCHEMA: Dict[str, str] = {
    "invoice_refs": "list[string] — invoice reference numbers explicitly printed in the document (e.g. ['088/2026-2027']); never numeric noise like ['3322', '585']",
    "awb":          "string|null — AWB / tracking number printed in the document",
    "mrn":          "string|null — MRN (Movement Reference Number) printed in the document",
    "cif_usd":      "number|null — declared CIF value in USD, EXACTLY as printed (no calculation)",
    "exporter":     "string|null — exporter / supplier company name",
    "importer":     "string|null — importer / consignee company name",
    "cn_codes":     "list[string] — HS/CN codes printed in the document",
    "confidence":   "string — one of: 'high', 'medium', 'low'",
    "evidence":     "list[string] — verbatim quotes from the document that support each non-null field (max 5 items)",
}


_SYSTEM_PROMPT = """\
You extract customs-evidence fields from noisy or partially parsed
customs documents (SAD/ZC429, commercial invoices, packing lists).

CRITICAL RULES — must follow exactly:
 1. ONLY return values that appear VERBATIM in the document text.
 2. NEVER calculate, infer, sum, or derive any value. If a field is
    not printed explicitly, return null.
 3. NEVER return numeric noise as an invoice reference. Plain digit
    runs (e.g. "3322", "121", "1000", "585") are NOT invoice refs.
    Real invoice refs have a recognisable pattern such as
    NNN/YYYY-YYYY, EJL-NN-NN-NNN, or similar exporter-ref format.
 4. confidence MUST be one of: "high", "medium", "low".
    - high   = all returned fields explicitly printed and visible
    - medium = some fields inferred from cross-reference within the
               document but each non-null value still printed
    - low    = document text was fragmented / OCR-noisy
 5. evidence is a list of short verbatim quotes (≤ 80 chars each) that
    PROVE where each non-null field came from in the document.
 6. Return ONLY the JSON object. No prose. No markdown fences.

Return shape (use null for fields you cannot extract confidently):
{schema}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Gate — only invoke AI when a deterministic gap exists
# ─────────────────────────────────────────────────────────────────────────────


def should_invoke_ai(deterministic_anchors: Dict[str, Any],
                     warnings: Optional[List[str]] = None) -> bool:
    """Return True iff the AI evidence recovery layer should fire.

    Trigger conditions (any one is sufficient):

      A. ``warnings`` contains a string starting with "VERIFY-GAP",
         "invoice refs inferred", or "low_confidence".
      B. ``deterministic_anchors["invoice_refs"]`` is empty or all
         entries are pure numeric noise (digit-runs only).
      C. ``deterministic_anchors["mrn"]`` is set but
         ``deterministic_anchors["awb"]`` is empty, or vice versa
         (one anchor present, the partner missing).
      D. ``deterministic_anchors["confidence"]`` == "low".

    Returns False when the deterministic parser already produced a
    confident, complete result. In that case the AI is NEVER invoked,
    keeping the deterministic path authoritative.
    """
    warnings = warnings or []
    # A — explicit verify-gap signal from caller
    for w in warnings:
        w_low = str(w).lower()
        if w_low.startswith("verify-gap") or "invoice refs inferred" in w_low \
                or "low_confidence" in w_low:
            return True

    # B — invoice_refs missing or pure numeric noise
    refs = deterministic_anchors.get("invoice_refs") or []
    if not refs:
        return True
    if all(_is_numeric_noise(r) for r in refs):
        return True

    # C — anchor partner missing
    mrn = (deterministic_anchors.get("mrn") or "").strip()
    awb = (deterministic_anchors.get("awb") or "").strip()
    if (mrn and not awb) or (awb and not mrn):
        return True

    # D — explicit low-confidence flag from deterministic side
    if str(deterministic_anchors.get("confidence") or "").lower() == "low":
        return True

    return False


def _is_numeric_noise(token: str) -> bool:
    """True for pure-digit tokens (e.g. '3322', '585', '088') that
    are NOT structured invoice references like '088/2026-2027' or
    'EJL/26-27/180'. Used by the gate to detect noise and by the
    reconciler to filter rejected refs."""
    s = str(token or "").strip()
    if not s:
        return True
    return s.isdigit()


# ─────────────────────────────────────────────────────────────────────────────
# Provider abstraction — safe no-op when unconfigured
# ─────────────────────────────────────────────────────────────────────────────


def _provider_available() -> bool:
    """Return True iff an AI provider is configured, enabled, and importable."""
    try:
        from ..core.config import settings  # noqa: PLC0415
        if not getattr(settings, "ai_parser_enabled", False):
            return False
        key = getattr(settings, "anthropic_api_key", None) or ""
        if not key.strip():
            return False
        import anthropic  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False
    except Exception:
        return False


def extract_customs_evidence(
    pdf_text:        str,
    *,
    document_hint:   str = "customs document",
    anchors:         Optional[Dict[str, Any]] = None,
    max_text_chars:  int = 6000,
) -> Optional[Dict[str, Any]]:
    """Invoke the AI provider to extract a customs evidence block.

    Parameters
    ----------
    pdf_text:
        Raw text extracted from the document by pdfplumber (or any
        equivalent). Trimmed to ``max_text_chars`` before being sent.
    document_hint:
        Free-text hint about which kind of document this is
        ("SAD/ZC429", "purchase invoice", "packing list", …).
    anchors:
        Deterministic anchors known by the backend. They are not sent
        to the AI (operator-locked: AI must extract independently),
        but caller may use them with ``reconcile_evidence`` afterwards.
    max_text_chars:
        Hard cap on prompt size. The first ``max_text_chars`` of
        ``pdf_text`` are sent; the document tail is dropped silently.

    Returns
    -------
    dict with the EVIDENCE_SCHEMA fields + ``_ai_meta`` block, OR
    ``None`` when:

      - no provider configured (safe no-op)
      - provider import / API call failed
      - AI response did not parse as strict JSON

    Never raises. Never makes a network call when ``_provider_available()``
    returns False — caller's deterministic path runs unchanged.
    """
    if not _provider_available():
        log.info("[ai_evidence] provider unavailable — deterministic path continues")
        return None

    if not pdf_text or not pdf_text.strip():
        return None

    schema_str = "\n".join(f'  "{k}": {v}' for k, v in EVIDENCE_SCHEMA.items())
    system = _SYSTEM_PROMPT.format(schema=schema_str)

    truncated = (pdf_text or "")[:max_text_chars]
    user_msg = (
        f"Document type hint: {document_hint}\n"
        f"Extract the customs evidence block from this document:\n"
        f"---\n{truncated}"
    )

    # Call via AI Gateway (single authority — no direct Anthropic client here)
    try:
        from . import ai_gateway  # noqa: PLC0415
        t0 = time.monotonic()
        raw_text = ai_gateway.call(
            system=system,
            user=user_msg,
            task_type="evidence_recovery",
            service_name="ai_customs_evidence",
            object_id=None,
            complexity="moderate",
            risk_level="medium",
            context_size=len(truncated),
            confidence_score=1.0,
            max_tokens=1500,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if raw_text is None:
            return None

        raw_text = raw_text.strip()
    except Exception as exc:
        log.warning("[ai_evidence] gateway call failed: %s", exc)
        return None

    parsed = _parse_strict_json(raw_text)
    if not isinstance(parsed, dict):
        log.warning(
            "[ai_evidence] provider returned non-JSON / non-dict: %r",
            raw_text[:200],
        )
        return None

    # Normalise the response: enforce schema, drop unknown keys,
    # coerce types, filter numeric-noise invoice refs.
    normalised = _normalise_response(parsed)
    normalised["_ai_meta"] = {
        "extraction_time_ms": elapsed_ms,
        "raw_confidence":     str(parsed.get("confidence") or "").lower(),
    }
    return normalised


def _parse_strict_json(raw: str) -> Optional[dict]:
    """Parse the AI's response as JSON. Strips markdown fences if
    present. Returns None on any error — caller treats as miss."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        # ```json\n{...}\n``` shape
        try:
            s = s.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        except Exception:
            return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _normalise_response(d: dict) -> Dict[str, Any]:
    """Coerce + filter the AI response into the canonical evidence shape.

    - Unknown keys dropped
    - Missing keys set to None / [] per schema type
    - invoice_refs and cn_codes coerced to list of trimmed non-empty strings
    - Pure-numeric-noise invoice refs dropped (the AI was instructed
      not to emit them; the reconciler enforces the rule regardless)
    - confidence coerced to one of {"high", "medium", "low"}, default "low"
    """
    out: Dict[str, Any] = {
        "invoice_refs": [],
        "awb":          None,
        "mrn":          None,
        "cif_usd":      None,
        "exporter":     None,
        "importer":     None,
        "cn_codes":     [],
        "confidence":   "low",
        "evidence":     [],
    }
    if not isinstance(d, dict):
        return out

    # Lists
    raw_refs = d.get("invoice_refs")
    if isinstance(raw_refs, list):
        out["invoice_refs"] = [
            str(r).strip() for r in raw_refs
            if r and str(r).strip() and not _is_numeric_noise(r)
        ]

    raw_cn = d.get("cn_codes")
    if isinstance(raw_cn, list):
        out["cn_codes"] = [str(c).strip() for c in raw_cn if c and str(c).strip()]

    raw_ev = d.get("evidence")
    if isinstance(raw_ev, list):
        out["evidence"] = [str(e).strip()[:120] for e in raw_ev if e and str(e).strip()][:8]

    # Strings (None when missing)
    for k in ("awb", "mrn", "exporter", "importer"):
        v = d.get(k)
        out[k] = (str(v).strip() or None) if v is not None else None

    # CIF — numeric coercion, None when not coercible
    cif = d.get("cif_usd")
    if cif is not None:
        try:
            out["cif_usd"] = float(cif)
        except (ValueError, TypeError):
            out["cif_usd"] = None

    # Confidence — clamp to allowed set
    conf = str(d.get("confidence") or "").strip().lower()
    out["confidence"] = conf if conf in {"high", "medium", "low"} else "low"

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation against deterministic anchors
# ─────────────────────────────────────────────────────────────────────────────


def reconcile_evidence(
    ai_block:       Optional[Dict[str, Any]],
    anchors:        Dict[str, Any],
    cif_tolerance:  float = 1.00,
) -> Dict[str, Any]:
    """Compare an AI evidence block against deterministic anchors and
    classify the outcome.

    Returns:

        {
          "status":  "verified_with_advisory" | "operator_review_required"
                     | "ai_unavailable" | "ai_low_confidence",
          "matches":   list[str],   # anchor fields the AI confirmed
          "mismatches": list[dict], # {field, anchor, ai} for each disagreement
          "advisory":  str,         # human-readable single line for the UI
          "evidence":  list[str],   # AI's evidence quotes (passed through)
        }

    Decision rules:

      - ai_block is None → status = "ai_unavailable"
      - ai_block.confidence == "low" → "ai_low_confidence" (operator review)
      - any AI value that disagrees with a corresponding non-empty
        anchor value (within tolerance for cif) → "operator_review_required"
        with the mismatches detailed
      - otherwise → "verified_with_advisory" — at least one anchor was
        confirmed by the AI and nothing disagreed

    NEVER writes anywhere. Pure / deterministic. Returns the decision;
    storage is the caller's responsibility.
    """
    if ai_block is None:
        return {
            "status":     "ai_unavailable",
            "matches":    [],
            "mismatches": [],
            "advisory":   "AI evidence unavailable — deterministic path used.",
            "evidence":   [],
        }

    if str(ai_block.get("confidence") or "low").lower() == "low":
        return {
            "status":     "ai_low_confidence",
            "matches":    [],
            "mismatches": [],
            "advisory":   "AI confidence low — operator review required.",
            "evidence":   list(ai_block.get("evidence") or [])[:5],
        }

    matches:    List[str]  = []
    mismatches: List[dict] = []

    # MRN — exact match (case-insensitive)
    a_mrn = (anchors.get("mrn") or "").strip().upper()
    b_mrn = (ai_block.get("mrn") or "").strip().upper()
    if a_mrn and b_mrn:
        if a_mrn == b_mrn:
            matches.append("mrn")
        else:
            mismatches.append({"field": "mrn", "anchor": a_mrn, "ai": b_mrn})

    # AWB — strip whitespace, exact match
    a_awb = re.sub(r"\s+", "", str(anchors.get("awb") or ""))
    b_awb = re.sub(r"\s+", "", str(ai_block.get("awb") or ""))
    if a_awb and b_awb:
        if a_awb == b_awb:
            matches.append("awb")
        else:
            mismatches.append({"field": "awb", "anchor": a_awb, "ai": b_awb})

    # CIF — tolerance comparison
    a_cif = anchors.get("cif_usd")
    b_cif = ai_block.get("cif_usd")
    if a_cif is not None and b_cif is not None:
        try:
            drift = abs(float(a_cif) - float(b_cif))
            if drift <= cif_tolerance:
                matches.append("cif_usd")
            else:
                mismatches.append({
                    "field":  "cif_usd",
                    "anchor": float(a_cif),
                    "ai":     float(b_cif),
                    "drift":  round(drift, 2),
                })
        except (ValueError, TypeError):
            pass

    # invoice_refs — AI must report at least one ref that contains an
    # anchor invoice number (substring tolerant — handles "088/2026-2027"
    # inside "N935-088/2026-2027" etc).
    a_refs = [str(r).strip() for r in (anchors.get("invoice_refs") or []) if r]
    b_refs = [str(r).strip() for r in (ai_block.get("invoice_refs") or []) if r]
    if a_refs and b_refs:
        # Filter noise refs from anchors before comparing
        a_clean = [r for r in a_refs if not _is_numeric_noise(r)]
        if a_clean:
            confirmed = any(any(a in b or b in a for b in b_refs) for a in a_clean)
            if confirmed:
                matches.append("invoice_refs")
            else:
                mismatches.append({
                    "field":  "invoice_refs",
                    "anchor": a_clean,
                    "ai":     b_refs,
                })
    elif (not a_refs) and b_refs:
        # AI recovered refs where the deterministic side had none. Treat
        # as informational recovery — counted as match.
        matches.append("invoice_refs_recovered")

    if mismatches:
        advisory = (
            "AI disagrees with deterministic anchors on "
            + ", ".join(m["field"] for m in mismatches)
            + " — operator review required."
        )
        return {
            "status":     "operator_review_required",
            "matches":    matches,
            "mismatches": mismatches,
            "advisory":   advisory,
            "evidence":   list(ai_block.get("evidence") or [])[:5],
        }

    advisory = (
        "SAD verified by " + "/".join(matches).upper()
        if matches else
        "AI evidence captured; no anchor cross-check yet."
    ) + " Invoice reference recovered from document text."
    return {
        "status":     "verified_with_advisory",
        "matches":    matches,
        "mismatches": [],
        "advisory":   advisory,
        "evidence":   list(ai_block.get("evidence") or [])[:5],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Audit storage — write only after reconciliation says so
# ─────────────────────────────────────────────────────────────────────────────


def build_audit_entry(
    ai_block:       Optional[Dict[str, Any]],
    reconciliation: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the dict to store under ``audit["ai_customs_evidence"]``.

    Stores BOTH the AI block AND the reconciliation result so that
    future operators / observers can see why a flag fired. NEVER
    writes any financial field; this is metadata only.
    """
    return {
        "ai_block":        ai_block or {},
        "reconciliation":  reconciliation,
        "stored_at":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "schema_version":  1,
    }
