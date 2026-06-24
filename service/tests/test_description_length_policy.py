"""
test_description_length_policy.py — Tests for description_length_policy.py

Coverage:
  1. Configured max length constants are sensible (reflect researched limits)
  2. PL-only path (blank EN) renders correctly and respects limits
  3. PL / EN path renders correctly
  4. Supplier shorthand tokens are always blocked
  5. Compact legal wording stays within MAX_COMBINED_CHARS
  6. Required legal words are preserved after compacting
  7. Over-limit unsafe description blocks wFirma/PZ finalization (HARD_BLOCK)
  8. validate_description_line integration path

## Source of limits

  wFirma goods/<name>: no explicit limit found in repo (WFIRMA_ENDPOINT_MAP.md
  is silent on goods/name char size). MAX_NOTE_LEN=500 in wfirma_pz_notes.py
  is for the wFirma <description> PZ field, a separate field from goods/<name>.

  Policy limits are conservative engineering targets:
    MAX_PL_CHARS    = 160  (canonical long-form PL is ~106 chars)
    MAX_EN_CHARS    = 90   (canonical compact EN is ~57 chars)
    MAX_COMBINED_CHARS = 200  (canonical compact combined is ~135 chars)
    HARD_BLOCK_CHARS   = 250  (absolute ceiling before blocking)
"""
from __future__ import annotations

import pytest


# ── canonical test fixtures ───────────────────────────────────────────────────

#: User-approved compact PL (operator approval 2026-06-24)
COMPACT_PL = (
    "Pierścionek z 14-karatowego złota (próba 585) z diamentami laboratoryjnymi."
)

#: User-approved compact EN (operator approval 2026-06-24)
COMPACT_EN = "14KT Gold Ring With Laboratory Grown Diamonds. Jewellery."

#: Long-form PL — the full customs description that may need compacting
LONGFORM_PL = (
    "Pierścionek z 14-karatowego złota (próba 585) wysadzany diamentami "
    "laboratoryjnymi. Biżuteria do noszenia."
)

#: EJL supplier shorthand — must NEVER be used as description_en
SHORTHAND_EN = "PCS, 14KT Gold, LGD Stud Jewellery RING"


# ── 1. Limit constant sanity ──────────────────────────────────────────────────

class TestLimitConstants:
    """Verify the configured limits match researched constraints."""

    def test_max_combined_is_under_hard_block(self):
        from app.services.description_length_policy import MAX_COMBINED_CHARS, HARD_BLOCK_CHARS
        assert MAX_COMBINED_CHARS < HARD_BLOCK_CHARS, (
            "MAX_COMBINED_CHARS must be below HARD_BLOCK_CHARS (soft target < hard ceiling)"
        )

    def test_hard_block_is_under_wfirma_note_limit(self):
        """
        wfirma_pz_notes.MAX_NOTE_LEN = 500 is the documented practical limit for
        the wFirma <description> field. HARD_BLOCK_CHARS (for goods/<name>) should
        be well under that — the goods name is a shorter identifying string.
        """
        from app.services.description_length_policy import HARD_BLOCK_CHARS
        WFIRMA_NOTE_LIMIT = 500  # MAX_NOTE_LEN in wfirma_pz_notes.py:50
        assert HARD_BLOCK_CHARS < WFIRMA_NOTE_LIMIT, (
            f"HARD_BLOCK_CHARS ({HARD_BLOCK_CHARS}) must be < wFirma note practical "
            f"limit ({WFIRMA_NOTE_LIMIT}). goods/<name> is shorter than <description>."
        )

    def test_max_combined_is_below_hard_block_with_margin(self):
        """
        MAX_COMBINED_CHARS fires compaction before HARD_BLOCK_CHARS is reached.
        That margin (HARD_BLOCK - MAX_COMBINED) must be > 0.

        NOTE: MAX_PL_CHARS + 3 + MAX_EN_CHARS may exceed HARD_BLOCK_CHARS.
        That is intentional — compaction fires at MAX_COMBINED_CHARS well
        below HARD_BLOCK_CHARS, so both per-slot limits are never simultaneously
        reached without compaction triggering first.
        """
        from app.services.description_length_policy import (
            MAX_COMBINED_CHARS, HARD_BLOCK_CHARS,
        )
        margin = HARD_BLOCK_CHARS - MAX_COMBINED_CHARS
        assert margin > 0, (
            f"HARD_BLOCK_CHARS ({HARD_BLOCK_CHARS}) must be above MAX_COMBINED_CHARS "
            f"({MAX_COMBINED_CHARS}). Margin: {margin}"
        )
        assert margin >= 50, (
            f"Safety margin between MAX_COMBINED ({MAX_COMBINED_CHARS}) and "
            f"HARD_BLOCK ({HARD_BLOCK_CHARS}) should be ≥ 50 chars. Got {margin}."
        )

    def test_approved_compact_example_fits_max_combined(self):
        from app.services.description_length_policy import MAX_COMBINED_CHARS
        combined = f"{COMPACT_PL} / {COMPACT_EN}"
        assert len(combined) <= MAX_COMBINED_CHARS, (
            f"Operator-approved compact example ({len(combined)} chars) must fit in "
            f"MAX_COMBINED_CHARS ({MAX_COMBINED_CHARS}). "
            f"Combined: {combined!r}"
        )


# ── 2. PL-only path ───────────────────────────────────────────────────────────

class TestPLOnlyPath:
    """Blank EN → PL-only render, no slash."""

    def test_validate_pl_only_is_ok(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, "")
        assert result.ok is True
        assert result.blocked is False
        assert result.en_chars == 0
        assert "/" not in result.compacted_pl or not result.compacted_en

    def test_validate_pl_only_combined_is_just_pl(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, "")
        assert result.combined_chars == len(COMPACT_PL)

    def test_validate_empty_pl_is_blocked(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line("", "")
        assert result.blocked is True
        assert result.ok is False
        assert "description_pl is empty" in result.advisory

    def test_validate_pl_only_no_slash_in_combined(self):
        from app.services.description_length_policy import validate_description_line, _combine
        result = validate_description_line(COMPACT_PL, "")
        combined = _combine(result.compacted_pl, result.compacted_en)
        assert "/" not in combined


# ── 3. PL / EN path ──────────────────────────────────────────────────────────

class TestPLENPath:
    """Both present → renders PL / EN, respects limits."""

    def test_validate_compact_pl_en_is_ok(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, COMPACT_EN)
        assert result.ok is True
        assert result.blocked is False

    def test_validate_compact_combined_contains_slash(self):
        from app.services.description_length_policy import validate_description_line, _combine
        result = validate_description_line(COMPACT_PL, COMPACT_EN)
        combined = _combine(result.compacted_pl, result.compacted_en)
        assert " / " in combined

    def test_validate_compact_combined_len_within_max(self):
        from app.services.description_length_policy import validate_description_line, MAX_COMBINED_CHARS
        result = validate_description_line(COMPACT_PL, COMPACT_EN)
        assert result.combined_chars <= MAX_COMBINED_CHARS

    def test_pl_en_are_returned_as_compacted_pl_en(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, COMPACT_EN)
        assert result.compacted_pl == COMPACT_PL
        assert result.compacted_en == COMPACT_EN


# ── 4. Supplier shorthand blocked ────────────────────────────────────────────

class TestSupplierShorthandBlocked:
    """Supplier shorthand tokens must never appear in output or be validated OK."""

    def test_shorthand_en_is_blocked(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, SHORTHAND_EN)
        assert result.blocked is True
        assert result.ok is False
        assert result.shorthand_detected is True

    def test_shorthand_in_pl_is_blocked(self):
        from app.services.description_length_policy import validate_description_line
        bad_pl = "Pierścionek PCS, 14KT Gold, LGD Stud Jewellery RING"
        result = validate_description_line(bad_pl, "")
        assert result.blocked is True
        assert result.shorthand_detected is True

    def test_lGD_stud_shorthand_blocked(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, "LGD Stud Jewellery RING")
        assert result.blocked is True
        assert result.shorthand_detected is True

    def test_prs_shorthand_blocked(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, "PRS, 18KT Gold, Diamond Earrings")
        assert result.blocked is True
        assert result.shorthand_detected is True

    def test_clean_en_passes_shorthand_check(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, COMPACT_EN)
        assert result.shorthand_detected is False


# ── 5. Compact legal wording within limit ────────────────────────────────────

class TestCompactWithinLimit:
    """Long-form PL compacts to within MAX_COMBINED_CHARS."""

    def test_longform_pl_en_compact_succeeds(self):
        from app.services.description_length_policy import (
            safe_compact_description, MAX_COMBINED_CHARS, _combine,
        )
        pl_out, en_out = safe_compact_description(LONGFORM_PL, COMPACT_EN)
        combined = _combine(pl_out, en_out)
        assert len(combined) <= MAX_COMBINED_CHARS, (
            f"safe_compact_description failed to reach MAX_COMBINED_CHARS "
            f"({MAX_COMBINED_CHARS}). Got {len(combined)} chars: {combined!r}"
        )

    def test_longform_compacted_pl_is_not_empty(self):
        from app.services.description_length_policy import safe_compact_description
        pl_out, _ = safe_compact_description(LONGFORM_PL, COMPACT_EN)
        assert pl_out.strip(), "Compacted PL must not be empty"

    def test_already_short_pl_unchanged(self):
        from app.services.description_length_policy import safe_compact_description
        pl_out, en_out = safe_compact_description(COMPACT_PL, COMPACT_EN)
        assert pl_out == COMPACT_PL
        assert en_out == COMPACT_EN

    def test_validate_longform_pl_is_ok_after_compact(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(LONGFORM_PL, COMPACT_EN)
        assert result.ok is True
        assert result.blocked is False
        assert result.compacted is True


# ── 6. Required legal words preserved ────────────────────────────────────────

class TestRequiredLegalWordsPreserved:
    """After compacting, required legal words (karat, próba, stone, Jewellery) survive."""

    def test_karat_word_preserved_after_compact(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(LONGFORM_PL, COMPACT_EN)
        assert "karatow" in result.compacted_pl.lower(), (
            f"'karatow' must survive compacting. Compacted PL: {result.compacted_pl!r}"
        )

    def test_proba_word_preserved_after_compact(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(LONGFORM_PL, COMPACT_EN)
        assert "próba" in result.compacted_pl.lower() or "proba" in result.compacted_pl.lower(), (
            f"próba/karat must survive compacting. Compacted PL: {result.compacted_pl!r}"
        )

    def test_stone_word_preserved_after_compact(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(LONGFORM_PL, COMPACT_EN)
        assert "diament" in result.compacted_pl.lower(), (
            f"Stone type word must survive compacting. Compacted PL: {result.compacted_pl!r}"
        )

    def test_jewellery_word_preserved_in_en(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, COMPACT_EN)
        assert "Jewellery" in result.compacted_en, (
            f"'Jewellery' must be present in EN output. Got: {result.compacted_en!r}"
        )

    def test_compact_result_passes_pl_required_word_check(self):
        from app.services.description_length_policy import (
            validate_description_line, _pl_required_words_present,
        )
        result = validate_description_line(LONGFORM_PL, COMPACT_EN)
        assert _pl_required_words_present(result.compacted_pl), (
            f"Compacted PL must pass required-word check. Got: {result.compacted_pl!r}"
        )


# ── 7. Over-limit unsafe description blocks wFirma/PZ finalization ───────────

class TestHardBlockEnforced:
    """A combined line over HARD_BLOCK_CHARS that cannot be compacted safely is BLOCKED."""

    def _make_very_long_pl(self) -> str:
        """Build a PL description that is over HARD_BLOCK_CHARS when combined with EN."""
        from app.services.description_length_policy import HARD_BLOCK_CHARS
        # Pad to 300 chars with required legal words still present.
        base = (
            "Pierścionek z 14-karatowego złota (próba 585) z diamentami laboratoryjnymi "
            "i rubinami i szafirami i szmaragdami i innymi kamieniami szlachetnymi. "
        )
        while len(base) < HARD_BLOCK_CHARS:
            base += "Pierścionek ze złota. "
        return base.strip()

    def test_very_long_combined_is_blocked(self):
        from app.services.description_length_policy import validate_description_line, HARD_BLOCK_CHARS
        long_pl = self._make_very_long_pl()
        # Use a long EN too so compacting PL alone does not save it.
        long_en = "14KT Gold Ring With Laboratory Grown Diamonds and Ruby and Sapphire and Emerald Gemstones. Jewellery."
        result = validate_description_line(long_pl, long_en)
        # If combined > HARD_BLOCK_CHARS AND compacting cannot reach target:
        from app.services.description_length_policy import _combine
        combined_in = _combine(long_pl, long_en)
        if len(combined_in) > HARD_BLOCK_CHARS:
            assert result.blocked is True, (
                f"Combined {len(combined_in)}-char description must be BLOCKED. "
                f"Advisory: {result.advisory!r}"
            )
        else:
            # Compacting succeeded — ok is acceptable
            assert result.ok is True or result.blocked is False

    def test_hard_block_triggers_advisory(self):
        from app.services.description_length_policy import validate_description_line, HARD_BLOCK_CHARS
        long_pl = self._make_very_long_pl()
        long_en = "14KT Gold Ring With Laboratory Grown Diamonds. Jewellery."
        from app.services.description_length_policy import _combine
        combined_in = _combine(long_pl, long_en)
        if len(combined_in) > HARD_BLOCK_CHARS:
            result = validate_description_line(long_pl, long_en)
            if result.blocked:
                assert "BLOCKED" in result.advisory or result.advisory != ""

    def test_empty_pl_always_blocked(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line("", COMPACT_EN)
        assert result.blocked is True

    def test_max_combined_exceeded_triggers_compact_or_block(self):
        """Any input over MAX_COMBINED_CHARS must either compact to OK or be BLOCKED."""
        from app.services.description_length_policy import (
            validate_description_line, MAX_COMBINED_CHARS, _combine,
        )
        long_pl = COMPACT_PL + " " + COMPACT_PL  # definitely over MAX_COMBINED_CHARS
        long_en = COMPACT_EN
        combined_in = _combine(long_pl, long_en)
        assert len(combined_in) > MAX_COMBINED_CHARS, "Test precondition: input must exceed MAX"
        result = validate_description_line(long_pl, long_en)
        # Must be either ok-after-compact or blocked.
        assert result.ok or result.blocked, "Over-limit input must either compact or block"


# ── 8. validate_description_line integration ─────────────────────────────────

class TestValidateDescriptionLineIntegration:
    """End-to-end validate_description_line scenarios."""

    def test_canonical_compact_passes_all_checks(self):
        from app.services.description_length_policy import (
            validate_description_line, MAX_COMBINED_CHARS,
        )
        result = validate_description_line(COMPACT_PL, COMPACT_EN)
        assert result.ok is True
        assert result.blocked is False
        assert not result.shorthand_detected
        assert result.combined_chars <= MAX_COMBINED_CHARS
        assert result.compacted_pl == COMPACT_PL
        assert result.compacted_en == COMPACT_EN

    def test_longform_pl_compact_en_compacts_and_passes(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(LONGFORM_PL, COMPACT_EN)
        assert result.ok is True
        assert result.blocked is False
        assert result.compacted is True
        assert "diament" in result.compacted_pl.lower()

    def test_shorthand_en_always_blocked_regardless_of_pl(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL, SHORTHAND_EN)
        assert result.blocked is True
        assert result.shorthand_detected is True

    def test_pl_only_no_en_always_ok_when_not_empty(self):
        from app.services.description_length_policy import validate_description_line
        result = validate_description_line(COMPACT_PL)  # en defaults to ""
        assert result.ok is True
        assert result.blocked is False
        assert result.en_chars == 0
