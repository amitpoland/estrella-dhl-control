"""PLAIN asserts the ABSENCE of stones. It must never win over a stone.

``STONE_ABBR`` holds both kinds of key because both answer questions about
stones: "DIA" names one, "PLAIN" says there are none — which is why it maps to
None. ``_STONE_KEYS`` sorts longest-first so the compound "DIA&CLS" beats "DIA",
and that ordering puts PLAIN (5 chars) ahead of DIAM (4), DIA (3) and CLS (3).

In a first-match-wins loop that meant a description carrying BOTH lost its
stones: the loop broke on PLAIN, took its None, and fell through to a fallback
that only searches for the full English word DIAMOND — never the abbreviation
that was actually present.

It is KEY order that decides, not text order. "DIA RING PLAIN BAND" failed
exactly as "PLAIN RING WITH DIA" did, so any multi-item description mixing a
plain piece with a set piece declared the whole block plain. On a customs
description.
"""
from __future__ import annotations

import pytest

from customs_description_engine import normalize_item_description
from description_grammar import STONE_ABBR


def stones(text):
    out = normalize_item_description(text)
    return out.get("stones_raw") or "", out.get("stones_pl") or ""


@pytest.mark.parametrize("text", [
    "18KT YELLOW GOLD PLAIN RING WITH DIA",      # plain before the stone
    "18KT YELLOW GOLD DIA RING PLAIN BAND",      # stone before plain
    "18KT GOLD PLAIN BANGLE / 18KT GOLD DIA PENDANT",
    "18KT GOLD DIA PENDANT / 18KT GOLD PLAIN BANGLE",
])
def test_a_stone_is_never_lost_to_the_word_plain(text):
    """THE regression, in both orders — because key order, not text order, was
    what decided."""
    raw, pl = stones(text)
    assert raw == "DIA", "stones lost to PLAIN in: %s" % text
    assert pl == "diamenty"


@pytest.mark.parametrize("abbr,expected_pl", [
    ("DIA", "diamenty"),
    ("DIAM", "diamenty"),
    ("CLS", "kamienie szlachetne"),
    ("DIA&CLS", "diamenty i kamienie szlachetne"),
    ("CZ", "cyrkonie"),
    ("RUBY", "rubiny"),
])
def test_every_stone_abbreviation_survives_the_word_plain(abbr, expected_pl):
    """Not a diamond-only defect: PLAIN outranked every abbreviation shorter
    than five characters, which is most of the vocabulary."""
    raw, pl = stones("18KT GOLD PLAIN RING WITH %s" % abbr)
    assert pl == expected_pl, "%s was swallowed by PLAIN" % abbr
    assert raw == abbr


def test_a_genuinely_plain_item_is_still_plain():
    """The other direction. Over-correcting here would put stones on plain
    goods — the same customs misstatement with the sign flipped."""
    raw, pl = stones("18KT YELLOW GOLD PLAIN RING")
    assert raw == "PLAIN"
    assert pl == ""


def test_an_item_with_no_stone_words_at_all_reports_no_stones():
    raw, pl = stones("18KT YELLOW GOLD RING")
    assert pl == ""


def test_the_compound_still_beats_its_parts():
    """The reason the list is sorted longest-first in the first place. This is
    what the fix must not break."""
    raw, _pl = stones("18KT GOLD RING WITH DIA&CLS")
    assert raw == "DIA&CLS", "longest-first ordering regressed"


def test_the_full_english_word_still_works():
    """The fallback path that used to mask the bug for DIAMOND specifically."""
    _raw, pl = stones("18KT YELLOW GOLD PLAIN RING WITH DIAMOND")
    assert pl == "diamenty"


def test_absence_keys_are_exactly_the_none_valued_ones():
    """ADVERSARY: the fix keys off 'STONE_ABBR value is falsy'. If someone adds
    a real stone with no Polish translation yet, it would silently become an
    absence marker and start losing stones again. Pin the vocabulary split so
    that addition fails here first."""
    absence = {k for k, v in STONE_ABBR.items() if not v}
    assert absence == {"PLAIN"}, (
        "a new None-valued key would be treated as 'no stones present': %r"
        % (absence - {"PLAIN"}))
