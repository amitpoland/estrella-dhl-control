"""excel_column_mapper.py — Three-tier advisory column-mapping for packing list headers.

Tier 1 — Deterministic alias:
    Exact normalised-key lookup in the caller-supplied field_aliases dict.
    Fastest path; result is authoritative.

Tier 2 — Rapidfuzz fuzzy:
    score >= 90  → accepted  (method="fuzzy";         included in build_col_map)
    80 <= s < 90 → warning   (method="fuzzy_warning"; advisory only, NOT in build_col_map)
    score < 80   → unresolved

Tier 3 — LLM advisory (optional, off by default):
    Advisory only.  Result carries method="llm" and is NEVER included in
    build_col_map.  Never writes to DB, never auto-creates business entities.
    _llm_suggest_header is a module-level function so tests can monkeypatch it.

Safety contract
---------------
build_col_map() only returns Tier-1 ("alias") and accepted Tier-2 ("fuzzy",
score >= 90) mappings.  Everything else is advisory — the caller must show
unresolved / warning mappings to an operator before acting on them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ColumnMapping",
    "CANONICAL_FIELDS",
    "map_all_headers",
    "build_col_map",
]

# ── Canonical field registry ─────────────────────────────────────────────────

CANONICAL_FIELDS: frozenset = frozenset({
    "design_no",          "batch_no",           "bag_id",             "tray_id",
    "item_type",          "line_position",       "invoice_line_position",
    "uom",                "quantity",
    "gross_weight",       "net_weight",
    "diamond_weight",     "color_weight",
    "metal",              "metal_color",         "karat",
    "quality_string",     "stone_type",
    "unit_price",         "total_value",         "size",
    "client_po",          "invoice_no",          "remarks",            "currency",
})

# ── Confidence thresholds ────────────────────────────────────────────────────

_FUZZY_ACCEPT   = 90.0   # score >= this → accepted, included in col_map
_FUZZY_WARN_LOW = 80.0   # score >= this (and < ACCEPT) → warning, advisory only

# ── Currency-annotation pre-processors (mirrors _map_headers logic) ──────────

_RE_PAREN_CCY = re.compile(
    r"\s*\(\s*(?:EUR|USD|PLN|GBP|CHF|JPY)\s*\)\s*", re.IGNORECASE
)
_RE_TRAIL_CCY = re.compile(
    r"\b(?:EUR|USD|PLN|GBP|CHF|JPY)\b\s*$", re.IGNORECASE
)


# ── Data contract ────────────────────────────────────────────────────────────

@dataclass
class ColumnMapping:
    col_index:       int
    original_header: str
    normalised:      str
    canonical_field: Optional[str]   # None when unresolved
    method:          str             # "alias"|"fuzzy"|"fuzzy_warning"|"llm"|"unresolved"
    confidence:      float           # 1.0 exact alias; 0-1 fuzzy/llm; 0.0 unresolved
    reason:          str


# ── Internal helpers ──────────────────────────────────────────────────────────

def _preprocess(raw: str) -> str:
    """Strip currency annotations and normalise to a snake_case lookup key.

    Matches the preprocessing in _map_headers() so Tier 1 and Tier 2 see
    identical normalised strings.
    """
    cleaned = _RE_PAREN_CCY.sub("", (raw or "").strip())
    cleaned = _RE_TRAIL_CCY.sub("", cleaned).strip()
    return re.sub(r"[^a-z0-9]", "_", cleaned.lower()).strip("_")


def _fuzzy_match(
    query: str,
    alias_keys: List[str],
) -> Tuple[Optional[str], float]:
    """Best rapidfuzz alias-key match.  Returns (key, score_0_100) or (None, 0)."""
    if not alias_keys or not query:
        return None, 0.0
    try:
        from rapidfuzz import fuzz, process as rf_process  # type: ignore
        result = rf_process.extractOne(query, alias_keys, scorer=fuzz.ratio)
        if result is None:
            return None, 0.0
        best_key, score, _ = result
        return best_key, float(score)
    except ImportError:
        return None, 0.0


def _llm_suggest_header(
    original_header: str,
    canonical_candidates: List[str],
) -> Dict[str, Any]:
    """LLM advisory fallback.

    Returns {"suggested_field": str|None, "confidence": float, "reason": str}.

    This is a module-level function so tests can replace it with monkeypatch:
        monkeypatch.setattr("app.services.excel_column_mapper._llm_suggest_header",
                            my_mock)

    Advisory only — callers must NEVER use the output to write to DB or
    auto-create business entities (PZ, products, customers, invoices, etc.).
    """
    try:
        import json as _json
        from .ai_gateway import call as _ai_call  # type: ignore
        user_msg = (
            f"Column header: \"{original_header}\"\n"
            f"Possible canonical field names: {canonical_candidates}\n\n"
            "Which canonical field best matches this header, if any?\n"
            "Respond with ONLY valid JSON — no markdown, no extra keys:\n"
            '{"suggested_field": "<field name or null>", '
            '"confidence": <float 0-1>, "reason": "<one sentence>"}'
        )
        raw = _ai_call(
            system=(
                "You are a data-mapping assistant for jewellery packing lists. "
                "Map Excel column headers to canonical field names. "
                "Return null for suggested_field if no confident match exists."
            ),
            user=user_msg,
            task_type="column_mapping",
            service_name="excel_column_mapper",
            object_id=(original_header or "")[:40],
            complexity="low",
            risk_level="low",
            context_size=len(original_header),
            confidence_score=1.0,
            max_tokens=150,
        )
        if not raw:
            return {"suggested_field": None, "confidence": 0.0, "reason": "llm_unavailable"}
        data = _json.loads(raw)
        suggested = data.get("suggested_field") or None
        if suggested and suggested not in canonical_candidates:
            suggested = None  # reject hallucinated field names
        return {
            "suggested_field": suggested,
            "confidence":      round(float(data.get("confidence", 0.0)), 4),
            "reason":          str(data.get("reason", "")),
        }
    except Exception as exc:
        return {
            "suggested_field": None,
            "confidence":      0.0,
            "reason":          f"llm_error: {exc}",
        }


# ── Public API ────────────────────────────────────────────────────────────────

def map_all_headers(
    raw_headers: List[str],
    field_aliases: Dict[str, str],
    *,
    llm_fallback: bool = False,
) -> List[ColumnMapping]:
    """Map every header through the three-tier pipeline.

    Parameters
    ----------
    raw_headers:
        Original header strings as read from the Excel/PDF file.
    field_aliases:
        Normalised-key → canonical-field-name dict
        (``_FIELD_ALIASES`` from invoice_packing_extractor, or any equivalent).
    llm_fallback:
        When True, unresolved headers after the fuzzy pass are submitted to
        the LLM advisory tier.  Default False to keep tests fast and
        deterministic without network access.

    Returns
    -------
    List[ColumnMapping], one entry per header in original column order.
    """
    alias_keys       = list(field_aliases.keys())
    canonical_list   = sorted(CANONICAL_FIELDS)

    result: List[ColumnMapping] = []

    for i, raw in enumerate(raw_headers):
        normalised = _preprocess(raw)

        # ── Tier 1: exact alias ───────────────────────────────────────────────
        if normalised in field_aliases:
            canonical = field_aliases[normalised]
            result.append(ColumnMapping(
                col_index=i,
                original_header=raw,
                normalised=normalised,
                canonical_field=canonical,
                method="alias",
                confidence=1.0,
                reason=f"Exact alias: '{normalised}' → '{canonical}'",
            ))
            continue

        # Empty / whitespace-only headers skip fuzzy (nothing useful to match)
        if not normalised:
            result.append(ColumnMapping(
                col_index=i,
                original_header=raw,
                normalised=normalised,
                canonical_field=None,
                method="unresolved",
                confidence=0.0,
                reason="Empty header",
            ))
            continue

        # ── Tier 2: rapidfuzz ─────────────────────────────────────────────────
        best_key, score = _fuzzy_match(normalised, alias_keys)

        if best_key is not None and score >= _FUZZY_ACCEPT:
            canonical = field_aliases[best_key]
            result.append(ColumnMapping(
                col_index=i,
                original_header=raw,
                normalised=normalised,
                canonical_field=canonical,
                method="fuzzy",
                confidence=round(score / 100.0, 4),
                reason=(
                    f"Fuzzy accept: '{normalised}' ~ '{best_key}' "
                    f"({score:.1f}) → '{canonical}'"
                ),
            ))
            continue

        if best_key is not None and score >= _FUZZY_WARN_LOW:
            canonical = field_aliases[best_key]
            result.append(ColumnMapping(
                col_index=i,
                original_header=raw,
                normalised=normalised,
                canonical_field=canonical,
                method="fuzzy_warning",
                confidence=round(score / 100.0, 4),
                reason=(
                    f"Fuzzy low-confidence: '{normalised}' ~ '{best_key}' "
                    f"({score:.1f}) — operator review required"
                ),
            ))
            continue

        # ── Tier 3: LLM advisory ──────────────────────────────────────────────
        if llm_fallback:
            llm = _llm_suggest_header(raw, canonical_list)
            suggested = llm.get("suggested_field") or None
            # Guard: only accept suggestions that name a known canonical field.
            # Rejects hallucinated field names even when the function is mocked.
            if suggested and suggested in CANONICAL_FIELDS:
                result.append(ColumnMapping(
                    col_index=i,
                    original_header=raw,
                    normalised=normalised,
                    canonical_field=suggested,
                    method="llm",
                    confidence=llm.get("confidence", 0.0),
                    reason=f"LLM advisory: {llm.get('reason', '')}",
                ))
                continue

        # ── Unresolved ────────────────────────────────────────────────────────
        reason_parts: List[str] = []
        if best_key is not None:
            reason_parts.append(
                f"best fuzzy: '{best_key}' @ {score:.1f} (< {_FUZZY_WARN_LOW})"
            )
        else:
            reason_parts.append("no fuzzy candidate")
        if llm_fallback:
            reason_parts.append("LLM returned no suggestion")

        result.append(ColumnMapping(
            col_index=i,
            original_header=raw,
            normalised=normalised,
            canonical_field=None,
            method="unresolved",
            confidence=0.0,
            reason="; ".join(reason_parts),
        ))

    return result


def build_col_map(mappings: List[ColumnMapping]) -> Dict[int, str]:
    """Return {col_index: canonical_field} for Tier-1 and accepted Tier-2 only.

    Excludes fuzzy_warning, llm, and unresolved — those are advisory and
    require operator review before inclusion in parse output.
    """
    return {
        m.col_index: m.canonical_field
        for m in mappings
        if m.method in ("alias", "fuzzy") and m.canonical_field is not None
    }
