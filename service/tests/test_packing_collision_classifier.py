"""A key collision is a question, never a verdict.

``packing_line_key`` is deliberately unscoped: the same commercial line arriving
under an advance pseudo-batch and under its real shipment batch must produce the
same key. That makes collisions expected, and it makes classifying them the
whole job. Getting this wrong in either direction is expensive — merging an
advance/final pair destroys the advance record, and linking two genuinely
different consignments silently halves a quantity.
"""
from __future__ import annotations

import pytest

from app.services.packing_db import (
    ADVANCE_FINAL,
    DUPLICATE,
    GENUINE,
    QUANTITY_MISMATCH,
    classify_collision_pair,
    classify_key_collision,
)


def _row(stage="final", file_hash="h1", total=21.0):
    return {"doc_stage": stage, "source_file_hash": file_hash,
            "doc_total_quantity": total}


def test_same_stage_is_a_duplicate():
    """The three production pairs: two 'final' documents, different hashes,
    one commercial line. The poorer document gets withdrawn."""
    assert classify_collision_pair(
        _row("final", "h1"), _row("final", "h2")) == DUPLICATE


def test_same_stage_duplicate_does_not_depend_on_the_hash():
    assert classify_collision_pair(
        _row("final", "h1"), _row("final", "h1")) == DUPLICATE


def test_same_bytes_under_two_stages_is_an_advance_final_pair():
    """The production case: ORDER CONFIRMATION _25-07_.xlsx ingested once as
    advance and once as final. Same file, two legitimate records — link them."""
    assert classify_collision_pair(
        _row("advance", "b99395a9"), _row("final", "b99395a9")) == ADVANCE_FINAL


def test_advance_final_wins_over_a_quantity_disagreement():
    """Rule order is load-bearing. The real pair disagrees on totals — 24 rows
    extracted as advance, 21 as final, from IDENTICAL bytes. That is a parser
    determinism defect, not two documents describing different goods. Blaming
    the goods for a bug in the extractor would hide the actual defect."""
    assert classify_collision_pair(
        _row("advance", "b99395a9", 24.0),
        _row("final", "b99395a9", 21.0)) == ADVANCE_FINAL


def test_different_stage_different_file_and_different_totals_is_a_mismatch():
    """Two different documents that disagree on what they contain. Flag it.
    Never merge — a merge here silently loses goods."""
    assert classify_collision_pair(
        _row("advance", "h1", 24.0), _row("final", "h2", 21.0)) == QUANTITY_MISMATCH


def test_different_stage_different_file_but_agreeing_totals_is_genuine():
    """Two documents, different bytes, same totals, one shared line key. Nothing
    explains that except the key being wrong. Escalate rather than guess."""
    assert classify_collision_pair(
        _row("advance", "h1", 21.0), _row("final", "h2", 21.0)) == GENUINE


def test_a_missing_hash_never_counts_as_a_match():
    """Two empty hashes are not 'the same file'. Absence is not equality."""
    assert classify_collision_pair(
        _row("advance", "", 21.0), _row("final", "", 21.0)) == GENUINE


@pytest.mark.parametrize("total_b", [21, 21.0, "21", "21.00"])
def test_total_quantity_spellings_are_one_total(total_b):
    assert classify_collision_pair(
        _row("advance", "h1", 21.0), _row("final", "h2", total_b)) == GENUINE


def test_a_set_takes_the_worst_class_any_pair_produces():
    """One clean pair does not excuse a bad one.

    Three rows, three pairs, three different answers:
      advance/b99395a9 + final/b99395a9  -> ADVANCE_FINAL (same bytes)
      final/b99395a9   + final/other     -> DUPLICATE     (same stage)
      advance/b99395a9 + final/other     -> QUANTITY_MISMATCH (21 vs 99)
    The set takes the worst, so a human looks at the mismatch rather than at a
    withdrawal that would have quietly resolved it.
    """
    rows = [_row("advance", "b99395a9", 21.0),
            _row("final", "b99395a9", 21.0),
            _row("final", "other", 99.0)]
    assert classify_key_collision(rows) == QUANTITY_MISMATCH


def test_three_rows_of_one_stage_are_still_just_duplicates():
    rows = [_row("final", "h1", 21.0),
            _row("final", "h2", 21.0),
            _row("final", "h3", 21.0)]
    assert classify_key_collision(rows) == DUPLICATE


def test_adding_a_third_document_usually_makes_things_worse():
    """Worth pinning because it is counter-intuitive. An advance/final pair is
    benign on its own, but a third document forms a NEW pair with the advance
    row — different stage, different bytes, agreeing totals — which is GENUINE.
    Reducing over pairs is what surfaces that; reducing over 'the majority
    class' would have hidden it."""
    benign = [_row("advance", "b99395a9", 21.0), _row("final", "b99395a9", 21.0)]
    assert classify_key_collision(benign) == ADVANCE_FINAL
    assert classify_key_collision(benign + [_row("final", "other", 21.0)]) == GENUINE


def test_genuine_outranks_everything():
    rows = [_row("advance", "b99395a9", 21.0),
            _row("final", "b99395a9", 21.0),
            _row("proforma", "other", 21.0)]
    assert classify_key_collision(rows) == GENUINE


def test_a_single_row_is_not_a_collision():
    assert classify_key_collision([_row()]) == ""
    assert classify_key_collision([]) == ""
