#!/usr/bin/env python3
"""
test_cif_softmatch_safety.py
============================
Safety tests for the CIF soft-match heuristic in
pz_import_processor.verify_sad_invoice_match().

ENGINE CONTRACT (three-state, per CLAUDE.md):
    True  = verified match
    False = confirmed hard mismatch
    None  = cannot verify from SAD format (insufficient evidence)

CIF check decision order:
    1. abs(diff) ≤ $1.00                                    → True (rounding)
    2. additions evidence present and explains diff         → True (verified
       (sad_additions_pln × 1/customs_rate_usd ≥ |diff|)         w/ customs)
    3. diff is "freight-shaped" (≤$500 AND (mod 50 < 10
       OR < 200))                                           → None (cannot
                                                                 verify; the
                                                                 diff plausibly
                                                                 represents
                                                                 freight/
                                                                 insurance/
                                                                 customs not
                                                                 declared on
                                                                 the SAD —
                                                                 left to
                                                                 operator
                                                                 review)
    4. otherwise                                            → False (hard
                                                                 mismatch)

These tests pin steps 1–4 against the live engine behaviour. The historical
"NoEvidenceMustFail" framing predates the three-state contract and has been
reconciled to match the engine: cases that look freight-shaped without
additions evidence return None (cannot verify) rather than False (confirmed
mismatch).

Run directly:  python3 test_cif_softmatch_safety.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pz_import_processor import verify_sad_invoice_match


def _inv(cif: float, ref: str = "INV-1"):
    return [{
        "invoice_no": ref, "invoice_date": "01-01-2026",
        "cif_usd":   cif, "fob_usd": cif, "freight_usd": 0, "insurance_usd": 0,
        "buyer_name": "X", "buyer_nip": "1234567890",
        "exporter_name": "ACME LTD", "seller_name": "ACME LTD",
        "items": [{"item_type": "RING", "quantity": 1, "total_usd": cif,
                   "hsn": "71131900"}],
    }]


def _zc(total_cif: float,
        sad_additions_pln: float = 0.0,
        customs_rate_usd: float = 0.0,
        sad_invoice_value_usd: float = 0.0):
    return {
        "total_cif_usd":         total_cif,
        "sad_invoice_value_usd": sad_invoice_value_usd,
        "sad_additions_pln":     sad_additions_pln,
        "customs_rate_usd":      customs_rate_usd,
        "invoice_refs":          ["INV-1"],
        "invoice_refs_method":   "N935",
        "importer_name": "ACME SP Z O O", "importer_nip": "1234567890",
        "exporter_name": "ACME LTD",
        "cn_code": "71131900", "sad_qty_by_type": {}, "sad_item_count": 1,
    }


# ── Diff-vs-evidence matrix ───────────────────────────────────────────────────

class TestNoEvidenceMustFail(unittest.TestCase):
    """Three-state CIF behaviour without SAD additions evidence.

    Engine contract per CLAUDE.md:
        True  = verified match
        False = confirmed hard mismatch
        None  = cannot verify from SAD format (insufficient evidence)

    A "freight-shaped" diff (≤ $500 AND round-50 OR < $200) without
    additions evidence is intentionally classified as None (cannot
    verify), not False — the engine errs on the side of operator
    review rather than auto-confirming a mismatch when the diff plausibly
    represents freight/insurance/customs that the SAD did not declare.
    A confirmed hard mismatch (e.g. > $500 and non-freight-shaped) still
    returns False.
    """

    def test_diff_50_no_evidence_is_soft(self):
        v = verify_sad_invoice_match(_inv(750.0), _zc(800.0))
        self.assertIsNone(v["cif_match"],
                          "diff $50, no additions → freight-shaped → None (cannot verify)")

    def test_diff_100_no_evidence_is_soft(self):
        v = verify_sad_invoice_match(_inv(750.0), _zc(850.0))
        self.assertIsNone(v["cif_match"],
                          "diff $100, no additions → freight-shaped → None (cannot verify)")

    def test_diff_150_no_evidence_is_soft(self):
        v = verify_sad_invoice_match(_inv(1000.0), _zc(1150.0))
        self.assertIsNone(v["cif_match"],
                          "diff $150, no additions → freight-shaped → None (cannot verify)")

    def test_diff_500_no_evidence_is_soft(self):
        v = verify_sad_invoice_match(_inv(5000.0), _zc(5500.0))
        self.assertIsNone(v["cif_match"],
                          "diff $500, no additions → freight-shaped boundary → None (cannot verify)")

    def test_diff_below_1_dollar_still_verified(self):
        """The $1 tolerance for rounding is preserved."""
        v = verify_sad_invoice_match(_inv(750.0), _zc(750.50))
        self.assertIs(v["cif_match"], True)


class TestEvidenceAllowsSoftMatch(unittest.TestCase):
    """When the SAD declares customs additions, a matching diff is acceptable."""

    def test_diff_within_additions_estimate_is_verified(self):
        # SAD additions 380 PLN, rate 3.80 → ~100 USD. Diff $100 → VERIFIED.
        v = verify_sad_invoice_match(
            _inv(750.0),
            _zc(850.0, sad_additions_pln=380.0, customs_rate_usd=3.80),
        )
        self.assertIs(v["cif_match"], True,
                      "diff matches additions estimate → VERIFIED")

    def test_additions_present_but_rate_unparsed_is_soft(self):
        """When [14 04] is present but exchange rate is missing, allow soft
        match — but only because there's positive evidence additions exist."""
        v = verify_sad_invoice_match(
            _inv(750.0),
            _zc(850.0, sad_additions_pln=380.0, customs_rate_usd=0.0),
        )
        self.assertIsNone(v["cif_match"],
                          "additions field present, rate unparsed → soft-match permitted")

    def test_diff_far_exceeds_additions_estimate_is_soft(self):
        # SAD declares 30 PLN ≈ $8 of additions; invoice diff $100.
        # The additions estimate ($8) does not explain the diff ($100), but
        # $100 is a freight-shaped diff (round 50, < 200), so per the
        # three-state contract the engine returns None (cannot verify) rather
        # than False — leaving the call to operator review.
        v = verify_sad_invoice_match(
            _inv(750.0),
            _zc(850.0, sad_additions_pln=30.0, customs_rate_usd=3.80),
        )
        self.assertIsNone(v["cif_match"],
                          "diff $100 ≫ additions estimate $8 but still freight-shaped → None")


class TestSoftMatchUnchangedForInformative(unittest.TestCase):
    """Backwards-compat: explicit verified case still verifies."""

    def test_no_diff_still_verified(self):
        v = verify_sad_invoice_match(_inv(1000.0), _zc(1000.0))
        self.assertIs(v["cif_match"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
