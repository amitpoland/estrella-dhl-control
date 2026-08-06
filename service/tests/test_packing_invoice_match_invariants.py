"""
Invariants for match_packing_to_invoice().

Product codes are minted on invoice lines and *copied* onto packing rows by the
matcher.  A packing row with product_code=None is therefore a placement failure,
not a generation failure — and the row that shows the failure is usually the
victim, not the culprit.  These tests pin the properties that make a silent
mis-placement impossible:

  * a discriminator present on both sides that disagrees vetoes the pair at
    EVERY confidence tier (a weaker tier may relax evidence that is missing,
    never evidence that contradicts);
  * assignment does not depend on the order the packing rows arrive in;
  * an aggregated invoice line cannot absorb more than it declares;
  * "matched" and "verified" are different things, and the row says which.

All fixtures are synthetic.  No client names, no real invoice numbers, no real
design numbers, no real AWB.
"""

import random

import pytest

from app.services.invoice_packing_extractor import (
    _CONF_AGGREGATE,
    _CONF_DIRECT,
    _CONF_QTY_RATE,
    _CONF_TYPE_QTY,
    _CONF_TYPE_QTY_METAL,
    _CONF_TYPE_QTY_RATE,
    _REVIEW_CONFIDENCE_FLOOR,
    match_packing_to_invoice,
)

INV = "TEST/00-00/001"


def _line(pos, item, qty, rate, desc="", inv=INV):
    """Synthetic invoice line — the authority that owns the product code."""
    return {
        "invoice_no": inv,
        "invoice_line_position": pos,
        "product_code": "{}-{}".format(inv, pos),
        "item_type": item,
        "quantity": qty,
        "rate_usd": rate,
        "total_value": round(qty * rate, 2),
        "description": desc,
    }


def _row(sr, item, qty, rate=0.0, metal="", karat="", inv=INV):
    """Synthetic packing row — per-piece, receives a code from a line."""
    return {
        "invoice_no": inv,
        "pack_sr": sr,
        "item_type": item,
        "quantity": qty,
        "unit_price": rate,
        "metal": metal,
        "karat": karat,
        "design_no": "D-{:03d}".format(sr),
    }


def _by_sr(matched):
    return {m["pack_sr"]: m for m in matched}


# ── The regression, generalised ───────────────────────────────────────────────

class TestConflictingEvidenceVetoesEveryTier:
    """
    A weaker tier must never claim a line that a stronger tier refused on the
    evidence.  Originally: a 14KT pendant whose own line was already taken fell
    through to the metal-blind "item type + quantity" tier and took the 925
    pendant's line, leaving the genuine 925 row with no product code at all.
    """

    def _fixture(self):
        lines = [
            _line(1, "PENDANT", 1, 106.00, desc="14KT/Y Plain PENDANT"),
            _line(2, "PENDANT", 1, 5.00, desc="SL925 SILVER Plain PENDANT"),
        ]
        rows = [
            _row(1, "PND", 1, metal="14KT/Y"),   # contests line 1
            _row(2, "PND", 1, metal="14KT/Y"),   # contests line 1 — one must lose
            _row(3, "PND", 1, metal="SL925/-"),  # genuinely owns line 2
        ]
        return rows, lines

    def test_genuine_row_keeps_its_line(self):
        rows, lines = self._fixture()
        out = _by_sr(match_packing_to_invoice(rows, lines))

        assert out[3]["product_code"] == "{}-2".format(INV)
        assert out[3]["extracted_confidence"] == pytest.approx(_CONF_TYPE_QTY_METAL)
        assert out[3]["requires_manual_review"] is False

    def test_surplus_row_surfaces_instead_of_stealing(self):
        rows, lines = self._fixture()
        out = _by_sr(match_packing_to_invoice(rows, lines))

        placed = [sr for sr in (1, 2) if out[sr]["product_code"]]
        assert len(placed) == 1, "only one row can own line 1"
        loser = 3 - placed[0]

        # The 925 line is metal-incompatible, so the surplus 14KT row has
        # nowhere legitimate to go.  It must say so, not take someone's line.
        assert out[loser]["product_code"] is None
        assert out[loser]["requires_manual_review"] is True
        assert out[loser]["match_strategy"] == "unmatched"

        # And it must not have taken the 925 line on the way out.
        assert out[loser]["product_code"] != "{}-2".format(INV)

    def test_holds_under_every_input_order(self):
        rows, lines = self._fixture()
        for order in ([0, 1, 2], [2, 1, 0], [1, 2, 0], [2, 0, 1]):
            out = _by_sr(match_packing_to_invoice([rows[i] for i in order], lines))
            assert out[3]["product_code"] == "{}-2".format(INV), order


class TestItemTypeVetoOnQtyRateTier:
    """
    The quantity+rate tier used to ignore item type entirely, so a ring at $318
    could take an earring line at $315 — inside the rate tolerance, wrong item.
    """

    def test_ring_does_not_take_an_earring_line(self):
        lines = [_line(1, "EARRINGS", 1, 315.00, desc="14KT/W EARRINGS")]
        rows = [_row(1, "RNG", 1, 318.00, metal="14KT/W")]

        out = _by_sr(match_packing_to_invoice(rows, lines))
        assert out[1]["product_code"] is None
        assert out[1]["requires_manual_review"] is True

    def test_but_still_matches_when_item_type_is_absent(self):
        """Relaxing MISSING evidence is exactly what the tier is for."""
        lines = [_line(1, "EARRINGS", 1, 315.00, desc="14KT/W EARRINGS")]
        rows = [_row(1, "", 1, 318.00)]

        out = _by_sr(match_packing_to_invoice(rows, lines))
        assert out[1]["product_code"] == "{}-1".format(INV)
        assert out[1]["extracted_confidence"] == pytest.approx(_CONF_QTY_RATE)
        assert out[1]["requires_manual_review"] is True   # below the floor


class TestRateVetoOnMetalTier:
    """
    item+qty+metal used to be accepted even when both sides carried a rate and
    the rates disagreed — i.e. it overrode the very evidence the stronger tier
    had just used to reject the pair.
    """

    def test_disagreeing_rate_blocks_the_metal_tier(self):
        lines = [_line(1, "RING", 2, 162.00, desc="14KT/W RING")]
        rows = [_row(1, "RNG", 2, 314.00, metal="14KT/W")]

        out = _by_sr(match_packing_to_invoice(rows, lines))
        assert out[1]["extracted_confidence"] <= _CONF_AGGREGATE
        assert out[1]["requires_manual_review"] is True


class TestTwoToneDescriptionIsNotAConflict:
    """
    A description may legitimately name more than one metal — a two-tone piece
    ("18KT Gold ... PT950 ...").  Reducing each side to a single canonical token
    picks whichever pattern is tried first, so such a line compared as PT950
    against an 18KT packing row and manufactured a conflict, vetoing a pair that
    agrees on every discriminator including metal.  Comparison is over token
    SETS: overlap is agreement, and only disjoint sets conflict.
    """

    def test_second_metal_in_the_description_does_not_veto_the_pair(self):
        lines = [_line(1, "RING", 1, 372.00, desc="PCS, 18KT Gold, Stud PT950 Jewell RING")]
        rows = [_row(1, "RNG", 1, 372.00, metal="18KT/YW", karat="18KT")]

        out = _by_sr(match_packing_to_invoice(rows, lines))
        assert out[1]["product_code"] == "{}-1".format(INV)
        assert out[1]["extracted_confidence"] == _CONF_TYPE_QTY_RATE
        assert out[1]["match_strategy"] == "type+qty+rate+metal"
        assert out[1]["requires_manual_review"] is False

    def test_genuinely_disjoint_metals_still_conflict(self):
        """Widening agreement must not cost the veto its teeth."""
        lines = [_line(1, "RING", 1, 372.00, desc="PCS, 18KT Gold, Stud PT950 Jewell RING")]
        rows = [_row(1, "RNG", 1, 372.00, metal="925", karat="925")]

        out = _by_sr(match_packing_to_invoice(rows, lines))
        assert out[1]["product_code"] is None
        assert out[1]["requires_manual_review"] is True


# ── Order independence ────────────────────────────────────────────────────────

class TestOrderIndependence:
    def _fixture(self):
        lines = [
            _line(1, "RING", 2, 162.00, desc="14KT/W RING"),
            _line(2, "RING", 17, 332.94, desc="14KT/W RING"),
            _line(3, "BRACELET", 6, 191.33, desc="SL925 BRACELET"),
            _line(4, "PENDANT", 1, 5.00, desc="SL925 PENDANT"),
        ]
        rows = (
            [_row(sr, "RNG", 1, rate, metal="14KT/W")
             for sr, rate in enumerate([717, 318, 445, 512, 289, 634, 401,
                                        158, 166, 523, 377, 298, 460], start=1)]
            + [_row(20, "BRC", 6, 191.33, metal="SL925/-")]
            + [_row(21, "PND", 1, 5.00, metal="SL925/-")]
        )
        return rows, lines

    def test_shuffling_rows_cannot_change_the_outcome(self):
        rows, lines = self._fixture()
        baseline = {
            sr: (m["product_code"], m["extracted_confidence"], m["match_strategy"])
            for sr, m in _by_sr(match_packing_to_invoice(rows, lines)).items()
        }

        for seed in range(12):
            shuffled = list(rows)
            random.Random(seed).shuffle(shuffled)
            out = {
                sr: (m["product_code"], m["extracted_confidence"], m["match_strategy"])
                for sr, m in _by_sr(match_packing_to_invoice(shuffled, lines)).items()
            }
            assert out == baseline, "assignment changed under seed {}".format(seed)

    def test_row_order_is_preserved_in_the_output(self):
        rows, lines = self._fixture()
        matched = match_packing_to_invoice(rows, lines)
        assert [m["pack_sr"] for m in matched] == [r["pack_sr"] for r in rows]

    def test_input_rows_are_not_mutated(self):
        rows, lines = self._fixture()
        before = [dict(r) for r in rows]
        match_packing_to_invoice(rows, lines)
        assert rows == before


# ── Capacity ──────────────────────────────────────────────────────────────────

class TestAggregateCapacity:
    """
    An aggregated invoice line summarises N packing rows.  Nothing used to stop
    the first such line swallowing every row while a larger line got none.
    """

    def _fixture(self):
        lines = [
            _line(1, "RING", 2, 162.00, desc="14KT/W RING"),    # small line
            _line(2, "RING", 17, 332.94, desc="14KT/W RING"),   # the big one
        ]
        rows = [
            _row(sr, "RNG", 1, rate, metal="14KT/W")
            for sr, rate in enumerate(
                [717, 318, 445, 512, 289, 634, 401, 158, 166, 523,
                 377, 298, 460, 355, 288, 604, 312, 149, 174], start=1)
        ]
        return rows, lines

    def test_no_line_exceeds_its_declared_quantity(self):
        rows, lines = self._fixture()
        matched = match_packing_to_invoice(rows, lines)

        per_line = {}
        for m in matched:
            if m["product_code"]:
                per_line[m["product_code"]] = per_line.get(m["product_code"], 0) + m["quantity"]

        assert per_line["{}-1".format(INV)] <= 2
        assert per_line["{}-2".format(INV)] <= 17

    def test_no_line_is_starved_and_no_row_is_orphaned(self):
        rows, lines = self._fixture()
        matched = match_packing_to_invoice(rows, lines)

        codes = [m["product_code"] for m in matched]
        assert all(c is not None for c in codes), "every row must find a home"
        assert set(codes) == {"{}-1".format(INV), "{}-2".format(INV)}, \
            "both lines must receive rows"

    def test_quantities_reconcile_exactly(self):
        rows, lines = self._fixture()
        matched = match_packing_to_invoice(rows, lines)

        per_line = {}
        for m in matched:
            per_line[m["product_code"]] = per_line.get(m["product_code"], 0) + m["quantity"]
        assert per_line["{}-1".format(INV)] == 2
        assert per_line["{}-2".format(INV)] == 17


# ── Review honesty ────────────────────────────────────────────────────────────

class TestReviewHonesty:
    def test_confidence_floor_sits_above_the_incident_tier(self):
        """
        The tier that caused the incident is item+qty with neither rate nor
        metal to corroborate it.  If the floor were at or below that tier, the
        same class of assignment would still pass as verified.
        """
        assert _REVIEW_CONFIDENCE_FLOOR > _CONF_TYPE_QTY
        assert _REVIEW_CONFIDENCE_FLOOR <= _CONF_TYPE_QTY_METAL

    def test_confidence_ladder_is_ordered(self):
        assert (_CONF_DIRECT > _CONF_TYPE_QTY_RATE > _CONF_TYPE_QTY_METAL
                > _CONF_TYPE_QTY > _CONF_QTY_RATE > _CONF_AGGREGATE > 0)

    def test_every_low_confidence_row_is_flagged(self):
        lines = [
            _line(1, "RING", 2, 162.00, desc="14KT/W RING"),
            _line(2, "RING", 17, 332.94, desc="14KT/W RING"),
            _line(3, "PENDANT", 1, 5.00, desc="SL925 PENDANT"),
        ]
        rows = [_row(sr, "RNG", 1, 300.00 + sr, metal="14KT/W") for sr in range(1, 20)]
        rows.append(_row(90, "PND", 1, metal="SL925/-"))
        rows.append(_row(91, "NECKLACE", 4, 88.00))          # nothing to match

        for m in match_packing_to_invoice(rows, lines):
            expected = bool(
                m["product_code"] is None
                or m["match_ambiguous"]
                or m["extracted_confidence"] < _REVIEW_CONFIDENCE_FLOOR
            )
            assert m["requires_manual_review"] is expected, m["pack_sr"]

    def test_high_confidence_rows_are_not_flagged(self):
        lines = [_line(1, "RING", 2, 162.00, desc="14KT/W RING")]
        rows = [_row(1, "RNG", 2, 162.00, metal="14KT/W")]

        out = _by_sr(match_packing_to_invoice(rows, lines))
        assert out[1]["extracted_confidence"] == pytest.approx(_CONF_TYPE_QTY_RATE)
        assert out[1]["match_strategy"] == "type+qty+rate+metal"
        assert out[1]["requires_manual_review"] is False


# ── Degenerate inputs ─────────────────────────────────────────────────────────

class TestDegenerateInputs:
    def test_no_invoice_lines_yields_unmatched_not_an_exception(self):
        rows = [_row(1, "RNG", 1, 100.0, metal="14KT/W")]
        matched = match_packing_to_invoice(rows, [])
        assert matched[0]["product_code"] is None
        assert matched[0]["requires_manual_review"] is True

    def test_no_packing_rows(self):
        assert match_packing_to_invoice([], [_line(1, "RING", 1, 10.0)]) == []

    def test_rows_from_another_invoice_never_borrow_a_line(self):
        lines = [_line(1, "RING", 1, 100.0, desc="14KT/W RING")]
        rows = [_row(1, "RNG", 1, 100.0, metal="14KT/W", inv="TEST/00-00/999")]

        out = _by_sr(match_packing_to_invoice(rows, lines))
        assert out[1]["product_code"] is None

    def test_direct_position_wins_and_is_exclusive(self):
        lines = [_line(1, "RING", 1, 100.0), _line(2, "RING", 1, 100.0)]
        rows = [
            dict(_row(1, "RNG", 1, 100.0), invoice_line_position=2),
            dict(_row(2, "RNG", 1, 100.0), invoice_line_position=2),
        ]
        out = _by_sr(match_packing_to_invoice(rows, lines))
        assert out[1]["product_code"] == "{}-2".format(INV)
        assert out[1]["extracted_confidence"] == pytest.approx(_CONF_DIRECT)
        assert out[2]["product_code"] != "{}-2".format(INV)
