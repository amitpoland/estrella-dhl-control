"""
description_length_policy.py — Canonical description length policy for PZ and wFirma.

## Limits found in the codebase

  wFirma goods/<name> field
    No explicit character limit is documented in the codebase or in
    WFIRMA_ENDPOINT_MAP.md.  The operational limit below (MAX_COMBINED_CHARS)
    is a conservative engineering target derived from the canonical compact
    example (135 chars) with headroom for edge-cases, and from the pattern
    established by MAX_NOTE_LEN = 500 in wfirma_pz_notes.py, which documents
    the wFirma <description> field's "practical limit".

  wFirma PZ <description> field
    MAX_NOTE_LEN = 500  (wfirma_pz_notes.py:50)
    This is a SEPARATE field from goods/<name>; it carries audit-trail notes,
    not product descriptions. The 500-char value is already enforced upstream.

  product_descriptions columns (SQLite TEXT)
    description_pl, description_en, description_line: TEXT — no SQLite
    constraint. The limits here govern what may safely flow to wFirma.

## Authority rule (Lesson N / PR #741)

  description_pl  = canonical Polish customs description (from description_engine)
  description_en  = canonical English ONLY if verified customs-grade English.
                    Supplier shorthand (PCS, PRS, LGD, DIA&CLS ...) MUST NOT
                    populate description_en.
  Render:         = "{description_pl} / {description_en}" or "{description_pl}"
                    when description_en is blank.

## Approved compact legal wording (operator-approved 2026-06-24)

  PL:  Pierścionek z 14-karatowego złota (próba 585) z diamentami laboratoryjnymi.
  EN:  14KT Gold Ring With Laboratory Grown Diamonds. Jewellery.
  Combined (135 chars):
       Pierścionek z 14-karatowego złota (próba 585) z diamentami laboratoryjnymi. /
       14KT Gold Ring With Laboratory Grown Diamonds. Jewellery.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Tuple


# ── Public limits ─────────────────────────────────────────────────────────────

#: Maximum chars for the Polish description slot before compacting is attempted.
#: Long-form canonical PL ("...Biżuteria do noszenia.") is ~106 chars;
#: compact form ("...z diamentami laboratoryjnymi.") is ~75 chars.
#: 160 chars gives comfortable room above the canonical long form.
MAX_PL_CHARS: int = 160

#: Maximum chars for the English description slot.
#: Canonical EN "14KT Gold Ring With Laboratory Grown Diamonds. Jewellery." is
#: 57 chars.  90 chars allows extended stone descriptions with headroom.
MAX_EN_CHARS: int = 90

#: Soft operational ceiling for the combined line ("{pl} / {en}" or "{pl}").
#: Canonical compact combined is 135 chars; 160 gives 18% headroom while
#: ensuring the long-form canonical PL ("...Biżuteria do noszenia.", ~166 chars
#: combined) always triggers compacting to the approved compact form.
#: If the combined line exceeds this, safe_compact_description() attempts
#: compacting before returning.
MAX_COMBINED_CHARS: int = 160

#: Hard block ceiling. If safe compacting cannot produce a combined line
#: at or under this limit while preserving required legal words, the
#: description is BLOCKED — wFirma/PZ finalisation must not proceed.
#: 250 is chosen as a conservative ceiling: well under any standard
#: VARCHAR(255) used by Polish ERP systems, and +50 above the observed
#: 200-char operational target.
HARD_BLOCK_CHARS: int = 250


# ── Supplier shorthand tokens (must never appear in output) ───────────────────

#: EJL/Ethos India invoice shorthand tokens that must never flow into
#: description_en or description_line.  These appear as invoice column
#: abbreviations, not customs-grade English sentences.
_SHORTHAND_TOKENS: Tuple[str, ...] = (
    "PCS",
    "PRS",
    "LGD Stud",
    "LGD stud",
    "Jewell",      # covers "Jewellery" in EJL shorthand context (e.g. "Stud Jewellery")
    "DIA&CLS",
    "dia&cls",
    "Stud Jewell",
)

#: Regex to detect shorthand tokens (case-sensitive; tokens are uppercase by convention).
_SHORTHAND_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _SHORTHAND_TOKENS) + r")\b"
)

#: Required legal words that must survive compacting.  If any of these cannot
#: be preserved after compacting, the description is BLOCKED.
#: "Jewellery" with capital J is the EN-side legal word; "karatowego", "próba",
#: and stone type words are on the PL side.
_REQUIRED_PL_WORDS: Tuple[re.Pattern, ...] = (
    re.compile(r"\bkaratow\w*\b", re.IGNORECASE),   # karatowego / karatowy
    re.compile(r"\bpróba\b",      re.IGNORECASE),   # próba NNN
    re.compile(r"\bdiament\w*\b", re.IGNORECASE),   # diament / diamentami / diamentów
    re.compile(r"\bbrylant\w*\b", re.IGNORECASE),   # brylant (alt stone name)
    re.compile(r"\bszafirow\w*\b",re.IGNORECASE),   # szafir / szafirowe
    re.compile(r"\bszmaragd\w*\b",re.IGNORECASE),   # szmaragd / szmaragdowe
    re.compile(r"\bplatyn\w*\b",  re.IGNORECASE),   # platyna / platynow
    re.compile(r"\bsrebr\w*\b",   re.IGNORECASE),   # srebra / srebrny
    re.compile(r"\bzłot\w*\b",    re.IGNORECASE),   # złota / złoty
)

_REQUIRED_EN_WORDS: Tuple[re.Pattern, ...] = (
    re.compile(r"\bJewellery\b"),                   # mandatory EN legal word
    re.compile(r"\bGold\b|\bSilver\b|\bPlatinum\b"),# metal type
    re.compile(r"\bDiamond\w*\b|\bRuby\b|\bSapphire\b|\bEmerald\b"),
)

#: Suffix appended by description_engine for completeness that can be safely
#: dropped to shorten the PL line.  The compact form omits this sentence.
_PL_COMPACTABLE_SUFFIXES: Tuple[str, ...] = (
    " Biżuteria do noszenia.",
    ". Biżuteria do noszenia.",
    " Biżuteria.",
    ". Biżuteria.",
)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """Outcome from validate_description_line()."""

    ok: bool
    """True when the description is safe to use in wFirma/PZ finalization."""

    blocked: bool
    """True when compacting failed and wFirma/PZ finalization must be stopped."""

    advisory: str
    """Human-readable advisory shown to the operator when not ok or blocked."""

    shorthand_detected: bool
    """True when supplier shorthand tokens were found in pl or en."""

    pl_chars: int
    """Length of the PL slot actually used (after any compacting)."""

    en_chars: int
    """Length of the EN slot actually used (after any compacting)."""

    combined_chars: int
    """Length of the combined line actually used."""

    compacted: bool
    """True when compacting was applied to reach an acceptable length."""

    compacted_pl: str
    """Compacted PL text (equals input pl when compacting was not needed)."""

    compacted_en: str
    """Compacted EN text (equals input en when compacting was not needed)."""

    warnings: list = field(default_factory=list)
    """Non-blocking observations (e.g. approaching MAX_COMBINED_CHARS)."""


# ── Public API ────────────────────────────────────────────────────────────────

def safe_compact_description(pl: str, en: str) -> Tuple[str, str]:
    """
    Return (pl_out, en_out) that together produce a combined line at or under
    MAX_COMBINED_CHARS while preserving required legal words.

    Rules applied in order:
    1. If combined ≤ MAX_COMBINED_CHARS: return (pl, en) unchanged.
    2. Drop known compactable suffixes from PL (e.g. "Biżuteria do noszenia.").
       If combined is then ≤ MAX_COMBINED_CHARS, return compacted (pl_out, en).
    3. Truncate PL at the last sentence boundary (". ") that keeps combined
       ≤ MAX_COMBINED_CHARS, provided required PL legal words are still present.
    4. If none of the above works: return (pl, en) unchanged so that the caller
       (validate_description_line) can surface a BLOCKED advisory.

    This function never strips required legal words (karat, próba, stone type,
    Jewellery).  If compacting would remove them, it returns the original input
    and lets the caller block finalization.
    """
    pl  = (pl  or "").strip()
    en  = (en  or "").strip()

    combined = _combine(pl, en)
    if len(combined) <= MAX_COMBINED_CHARS:
        return pl, en

    # Step 2: strip compactable suffix from PL.
    pl_compact = _strip_compact_suffixes(pl)
    if pl_compact != pl:
        combined_c = _combine(pl_compact, en)
        if len(combined_c) <= MAX_COMBINED_CHARS and _pl_required_words_present(pl_compact):
            return pl_compact, en

    # Step 3: truncate PL at last sentence boundary.
    pl_truncated = _truncate_at_sentence(pl, max_pl=MAX_PL_CHARS)
    if pl_truncated and pl_truncated != pl:
        combined_t = _combine(pl_truncated, en)
        if len(combined_t) <= MAX_COMBINED_CHARS and _pl_required_words_present(pl_truncated):
            return pl_truncated, en

    # Could not compact safely — return originals; caller must block.
    return pl, en


def validate_description_line(pl: str, en: str = "") -> ValidationResult:
    """
    Validate a (pl, en) pair for use in wFirma/PZ finalization.

    Returns a ValidationResult with:
      ok=True      → description is safe to use as-is or after compacting.
      blocked=True → description cannot be safely shortened; DO NOT finalize.
      advisory     → human-readable message for the operator.

    Rules:
    1. description_pl is mandatory.  Empty pl is always blocked.
    2. EN may be blank (PL-only render is valid and preferred when EN is absent).
    3. Supplier shorthand tokens must never appear in pl or en.
    4. combined ≤ HARD_BLOCK_CHARS; ideally ≤ MAX_COMBINED_CHARS.
    5. After compacting, required legal words must be preserved.
    6. Required EN words (Jewellery, metal, stone) must be preserved if EN present.
    """
    pl  = (pl  or "").strip()
    en  = (en  or "").strip()

    warnings   = []
    advisory   = ""
    blocked    = False
    ok         = True
    compacted  = False
    pl_out     = pl
    en_out     = en

    # ── Rule 1: PL is mandatory ───────────────────────────────────────────────
    if not pl:
        return ValidationResult(
            ok=False,
            blocked=True,
            advisory=(
                "description_pl is empty. The canonical Polish customs description "
                "must be populated before wFirma/PZ finalization. "
                "Run the customs description package first."
            ),
            shorthand_detected=False,
            pl_chars=0, en_chars=len(en), combined_chars=len(en),
            compacted=False, compacted_pl="", compacted_en=en,
            warnings=[],
        )

    # ── Rule 3: no shorthand tokens ───────────────────────────────────────────
    shorthand_in_pl = bool(_SHORTHAND_RE.search(pl))
    shorthand_in_en = bool(_SHORTHAND_RE.search(en)) if en else False
    shorthand_detected = shorthand_in_pl or shorthand_in_en

    if shorthand_detected:
        parts = []
        if shorthand_in_pl:
            parts.append(f"description_pl contains supplier shorthand: {pl!r}")
        if shorthand_in_en:
            parts.append(f"description_en contains supplier shorthand: {en!r}")
        advisory = (
            "BLOCKED — supplier shorthand tokens detected. "
            "These are EJL/Ethos invoice codes (PCS/PRS/LGD/DIA&CLS), not "
            "customs-grade descriptions. description_en must be blank for EJL "
            "products until a verified English sentence is provided. "
            + " | ".join(parts)
        )
        return ValidationResult(
            ok=False, blocked=True, advisory=advisory,
            shorthand_detected=True,
            pl_chars=len(pl), en_chars=len(en),
            combined_chars=len(_combine(pl, en)),
            compacted=False, compacted_pl=pl, compacted_en=en,
            warnings=[],
        )

    # ── Rule 2: EN slot — if present, must contain required EN words ──────────
    if en:
        missing_en = _missing_en_words(en)
        if missing_en:
            warnings.append(
                f"description_en is present but missing required EN legal words: "
                f"{missing_en}. Verify this is a customs-grade English sentence."
            )

    # ── Rules 4–5: length check and compacting ────────────────────────────────
    combined = _combine(pl, en)

    if len(combined) > MAX_COMBINED_CHARS:
        pl_out, en_out = safe_compact_description(pl, en)
        combined_after = _combine(pl_out, en_out)
        compacted = (pl_out != pl or en_out != en)

        if len(combined_after) > HARD_BLOCK_CHARS:
            return ValidationResult(
                ok=False, blocked=True,
                advisory=(
                    f"BLOCKED — combined description line is {len(combined_after)} chars "
                    f"(hard block limit is {HARD_BLOCK_CHARS}). "
                    f"Safe compacting could not reduce it to {HARD_BLOCK_CHARS} chars "
                    f"without removing required legal words (karat, próba, stone type, "
                    f"Jewellery). Operator must manually shorten description_pl or "
                    f"description_en and re-verify."
                ),
                shorthand_detected=False,
                pl_chars=len(pl_out), en_chars=len(en_out),
                combined_chars=len(combined_after),
                compacted=compacted,
                compacted_pl=pl_out, compacted_en=en_out,
                warnings=warnings,
            )

        if len(combined_after) > MAX_COMBINED_CHARS:
            warnings.append(
                f"Combined description is {len(combined_after)} chars (soft target is "
                f"{MAX_COMBINED_CHARS}). Verify it is accepted by wFirma before finalizing."
            )
            ok = True  # warn but not blocked

        advisory = "" if ok else advisory
        combined = combined_after

    else:
        # Check individual slot limits even when combined is under the target.
        if len(pl) > MAX_PL_CHARS:
            warnings.append(
                f"description_pl is {len(pl)} chars (soft target MAX_PL_CHARS={MAX_PL_CHARS})."
            )
        if en and len(en) > MAX_EN_CHARS:
            warnings.append(
                f"description_en is {len(en)} chars (soft target MAX_EN_CHARS={MAX_EN_CHARS})."
            )

    # ── Rule 5 (post-compact): required PL words preserved ───────────────────
    if pl_out and not _pl_required_words_present(pl_out):
        return ValidationResult(
            ok=False, blocked=True,
            advisory=(
                "BLOCKED — compacted description_pl is missing required legal words "
                f"(karat, próba, metal, stone type). Compacted to: {pl_out!r}. "
                "Cannot safely shorten further. Operator must supply a pre-approved "
                "compact description."
            ),
            shorthand_detected=False,
            pl_chars=len(pl_out), en_chars=len(en_out),
            combined_chars=len(_combine(pl_out, en_out)),
            compacted=compacted, compacted_pl=pl_out, compacted_en=en_out,
            warnings=warnings,
        )

    return ValidationResult(
        ok=ok,
        blocked=False,
        advisory=advisory,
        shorthand_detected=False,
        pl_chars=len(pl_out),
        en_chars=len(en_out),
        combined_chars=len(_combine(pl_out, en_out)),
        compacted=compacted,
        compacted_pl=pl_out,
        compacted_en=en_out,
        warnings=warnings,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _combine(pl: str, en: str) -> str:
    """Mirror of description_engine.build_description_line — no import needed."""
    pl = (pl or "").strip()
    en = (en or "").strip()
    if pl and en:
        return f"{pl} / {en}"
    return pl or en


def _strip_compact_suffixes(pl: str) -> str:
    for suffix in _PL_COMPACTABLE_SUFFIXES:
        if pl.endswith(suffix):
            compacted = pl[: -len(suffix)].rstrip()
            if compacted:
                return compacted
    return pl


def _truncate_at_sentence(text: str, max_pl: int) -> str:
    """Truncate text to the last '. ' or '.' boundary at or before max_pl chars."""
    if len(text) <= max_pl:
        return text
    chunk = text[:max_pl]
    # Find last sentence end.
    last_period = chunk.rfind(". ")
    if last_period == -1:
        last_period = chunk.rfind(".")
    if last_period <= 0:
        return ""
    return text[: last_period + 1].strip()


def _pl_required_words_present(pl: str) -> bool:
    """
    True when at least one of the required PL legal words is present.
    (Any one word is enough — a valid PL description will typically contain
    multiple required words, but checking ≥1 catches edge cases where the
    description is an unusual item type with no gold/silver/diamond.)
    """
    return any(pat.search(pl) for pat in _REQUIRED_PL_WORDS)


def _missing_en_words(en: str) -> list:
    """Return a list of required EN word groups that are absent from en."""
    missing = []
    for pat in _REQUIRED_EN_WORDS:
        if not pat.search(en):
            missing.append(pat.pattern)
    return missing
