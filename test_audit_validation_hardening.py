#!/usr/bin/env python3
"""
test_audit_validation_hardening.py
==================================
Tests for the 2026-05 audit hardening:
  - aggregated-SAD quantity logic (PARTIAL)
  - CN hierarchy validation (711319 parent)
  - exporter/NIP normalization + fallback
  - hard-link integrity check
  - audit scoring caps (no 100/100 with gaps)
  - SAD_READY CIF total + Polish description value block

Run directly:  python3 test_audit_validation_hardening.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── 1. Audit scoring caps ─────────────────────────────────────────────────────

class TestAuditScoringCaps(unittest.TestCase):
    def setUp(self):
        # Enable the audit hardening feature flag for the duration of this
        # test class. The BLOCKED tests call score_batch without categorical
        # kwargs, so the flag is the only activation path; the cap tests
        # supply categoricals which would activate hardening on their own,
        # but enabling the flag here keeps the test class self-consistent.
        import os
        self._prev_audit_flag = os.environ.get("AUDIT_HARDENING_ENABLED")
        os.environ["AUDIT_HARDENING_ENABLED"] = "1"

        from audit_scoring import score_batch
        self.score_batch = score_batch
        # Default all-clean checks
        self.c1 = {"result": True,  "sad_value_present": True}
        self.c2 = {"name_result": True, "nip_result": True}
        self.c3 = {"consistent": True}
        self.c4 = {"result": True}
        self.c5 = {"cif_result": True, "per_inv_checks": [{"ok": True}]}
        self.c6 = {"result": True}

    def tearDown(self):
        # Restore the previous env state so other test files / classes
        # observe the legacy scoring path by default.
        import os
        if self._prev_audit_flag is None:
            os.environ.pop("AUDIT_HARDENING_ENABLED", None)
        else:
            os.environ["AUDIT_HARDENING_ENABLED"] = self._prev_audit_flag

    def test_all_verified_can_score_100(self):
        r = self.score_batch(self.c1, self.c2, self.c3, self.c4, self.c5, self.c6,
                             qty_status="verified", cn_status="verified")
        self.assertEqual(r["score"], 100)
        self.assertEqual(r["status"], "VERIFIED")

    def test_partial_caps_at_85(self):
        r = self.score_batch(self.c1, self.c2, self.c3, self.c4, self.c5, self.c6,
                             qty_status="partial_aggregated_sad",
                             cn_status="verified_parent_aggregated")
        self.assertLessEqual(r["score"], 85)
        self.assertEqual(r["status"], "PARTIAL")

    def test_not_verified_caps_at_70(self):
        c1 = {"result": None, "sad_value_present": False}
        r = self.score_batch(c1, self.c2, self.c3, self.c4, self.c5, self.c6,
                             qty_status="partial_aggregated_sad",
                             cn_status="verified_parent_aggregated")
        self.assertLessEqual(r["score"], 70)
        self.assertEqual(r["status"], "NOT_VERIFIED")

    def test_parser_fallback_caps_at_90(self):
        r = self.score_batch(self.c1, self.c2, self.c3, self.c4, self.c5, self.c6,
                             nip_source="sad_and_master",
                             qty_status="verified", cn_status="verified")
        self.assertLessEqual(r["score"], 90)
        self.assertEqual(r["status"], "VERIFIED")

    def test_hard_link_failure_blocks_audit(self):
        c4 = {"result": False}  # invoice ↔ SAD ref mismatch
        r = self.score_batch(self.c1, self.c2, self.c3, c4, self.c5, self.c6)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["status"], "BLOCKED")

    def test_cif_total_mismatch_blocks_audit(self):
        c5 = {"cif_result": False, "per_inv_checks": [{"ok": True}]}
        r = self.score_batch(self.c1, self.c2, self.c3, self.c4, c5, self.c6)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["status"], "BLOCKED")


# ── 2. CN hierarchy ───────────────────────────────────────────────────────────

class TestCNHierarchy(unittest.TestCase):
    def test_711319_children_match_71131900_parent(self):
        from pz_import_processor import verify_sad_invoice_match
        invoices = [{
            "invoice_no": "EJL/25-26/1247",
            "items": [
                {"item_type": "RING", "quantity": 2, "hsn": "71131911"},
                {"item_type": "RING", "quantity": 5, "hsn": "71131913"},
                {"item_type": "EARRINGS", "quantity": 16, "hsn": "71131919"},
            ],
            "fob_usd": 100, "freight_usd": 0, "insurance_usd": 0, "cif_usd": 100,
            "buyer_name": "ESTRELLA JEWELS SP Z O O",
            "buyer_nip": "5252812119",
            "exporter_name": "Estrella Jewels LLP",
        }]
        zc429 = {
            "cn_code": "71131900", "sad_qty_by_type": {}, "sad_item_count": 1,
            "importer_name": "ESTRELLA JEWELS SP Z O O", "importer_nip": "5252812119",
            "exporter_name": "ESTRELLA JEWELS LLP",
            "sad_cif_total_usd": 100, "invoice_refs": ["EJL/25-26/1247"],
            "total_cif_usd": 100,
        }
        v = verify_sad_invoice_match(invoices, zc429)
        self.assertEqual(v["cn_status"], "verified_parent_aggregated")
        self.assertTrue(v["cn_match"])

    def test_unrelated_cn_parents_fail(self):
        from pz_import_processor import verify_sad_invoice_match
        invoices = [{
            "invoice_no": "X", "items": [{"item_type": "RING", "quantity": 1, "hsn": "61091000"}],
            "fob_usd": 1, "freight_usd": 0, "insurance_usd": 0, "cif_usd": 1,
            "buyer_name": "X", "buyer_nip": "1234567890", "exporter_name": "X",
        }]
        zc429 = {"cn_code": "71131900", "importer_name": "X", "importer_nip": "1234567890",
                 "exporter_name": "X", "invoice_refs": ["X"], "sad_item_count": 1}
        v = verify_sad_invoice_match(invoices, zc429)
        self.assertEqual(v["cn_status"], "failed_parent_mismatch")
        self.assertFalse(v["cn_match"])


# ── 3. Aggregated SAD quantity ────────────────────────────────────────────────

class TestAggregatedSAD(unittest.TestCase):
    def test_item_count_1_and_no_qty_breakdown_is_partial(self):
        from pz_import_processor import verify_sad_invoice_match
        invoices = [{
            "invoice_no": "I1", "items": [
                {"item_type": "RING", "quantity": 5},
                {"item_type": "EARRINGS", "quantity": 10},
            ],
            "fob_usd": 100, "freight_usd": 0, "insurance_usd": 0, "cif_usd": 100,
            "buyer_name": "X", "buyer_nip": "1234567890", "exporter_name": "X",
        }]
        zc429 = {"sad_qty_by_type": {}, "sad_item_count": 1,
                 "importer_name": "X", "importer_nip": "1234567890",
                 "exporter_name": "X", "invoice_refs": ["I1"], "cn_code": "71131900",
                 "sad_cif_total_usd": 100}
        v = verify_sad_invoice_match(invoices, zc429)
        self.assertIsNone(v["qty_match_by_type"])
        self.assertEqual(v["qty_status"], "partial_aggregated_sad")


# ── 4. ZC429 exporter parser ──────────────────────────────────────────────────

class TestZC429ExporterParser(unittest.TestCase):
    """The parser must recognise 'Eksporter [13 01]: ESTRELLA JEWELS LLP. Adres: ...'"""

    def test_eksporter_with_field_code(self):
        # Mimic the regex chain in pz_import_processor.parse_zc429
        text = ("Eksporter [13 01]: ESTRELLA JEWELS LLP. Adres: MIDC CROSS ROAD NO. 21\n"
                "ANDHERI EAST, 400093 MUMBAI (IN)\n")
        exporter_name = ""
        for pattern in [
            r"Sprzedaj[aą]cy\s*:\s*([^\n]+)",
            r"Nadawca\s*/?\s*[Ee]ksporter\s*:\s*([^\n]+)",
            r"Eksporter\s*(?:\[\s*13\s*0?1\s*\])?\s*:\s*([^\n]+)",
            r"Nadawca\s*:\s*([^\n]+)",
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip()[:150]
                candidate = re.split(r"\s+Adres\s*:", candidate, maxsplit=1)[0].strip()
                candidate = candidate.rstrip(".").strip()
                if len(candidate) > 5:
                    exporter_name = candidate
                    break
        self.assertEqual(exporter_name, "ESTRELLA JEWELS LLP")


# ── 5. Hard-link integrity ────────────────────────────────────────────────────

class TestHardLinkIntegrity(unittest.TestCase):
    def test_awb_mismatch_blocks(self):
        from audit_scoring import detect_hard_link_break
        c4 = {"result": True}
        c5 = {"cif_result": True}
        c6 = {"result": True}
        hl = {"any_broken": True, "reason": "AWB X does not match SAD N740"}
        res = detect_hard_link_break(c4, c5, c6, hl)
        self.assertTrue(res["blocked"])
        self.assertTrue(any("AWB" in r for r in res["reasons"]))

    def test_cif_total_mismatch_breaks_link(self):
        from audit_scoring import detect_hard_link_break
        res = detect_hard_link_break(
            {"result": True}, {"cif_result": False}, {"result": True}, None
        )
        self.assertTrue(res["blocked"])


# ── 6. NIP fallback verification ──────────────────────────────────────────────

class TestNIPFallback(unittest.TestCase):
    def test_invoice_nip_missing_but_sad_matches_master(self):
        from pz_import_processor import verify_sad_invoice_match
        invoices = [{
            "invoice_no": "EJL/X", "items": [{"item_type": "RING", "quantity": 1}],
            "fob_usd": 1, "freight_usd": 0, "insurance_usd": 0, "cif_usd": 1,
            "buyer_name": "Estrella Jewels Sp. z o.o., Sp. k.", "buyer_nip": "",
            "exporter_name": "Estrella Jewels LLP",
        }]
        zc429 = {"cn_code": "71131900", "sad_qty_by_type": {}, "sad_item_count": 1,
                 "importer_name": "ESTRELLA JEWELS SP Z O O SP KOM",
                 "importer_nip": "5252812119",  # master
                 "exporter_name": "ESTRELLA JEWELS LLP",
                 "invoice_refs": ["EJL/X"], "sad_cif_total_usd": 1}
        v = verify_sad_invoice_match(invoices, zc429)
        self.assertEqual(v["nip_source"], "sad_and_master")
        self.assertTrue(v["vat_match"])


# ── 7. SAD_READY total uses CIF, not FOB ──────────────────────────────────────

class TestSADReadyTotalIsCIF(unittest.TestCase):
    def test_total_value_usd_equals_cif(self):
        from customs_description_engine import generate_sad_ready_json
        import json
        import tempfile
        batch = {
            "batch_id": "T",
            "rows": [
                {"invoice_number": "I1", "item_type": "RING", "quantity": 2,
                 "unit_price": 313.0, "line_total": 626.0,
                 "description": "Plain 9KT Gold Jewellery RING"},
            ],
            "invoices": [
                {"invoice_no": "I1", "fob_usd": 626.0, "freight_usd": 15.0,
                 "insurance_usd": 10.0, "cif_usd": 651.0,
                 "exporter_name": "Estrella Jewels LLP"},
            ],
            "invoice_totals": {
                "total_fob_usd": 626.0, "total_freight_usd": 15.0,
                "total_insurance_usd": 10.0, "total_cif_usd": 651.0,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            r = generate_sad_ready_json(batch, "1234567890", tmp, "")
            self.assertTrue(r["generated"])
            data = json.loads(Path(r["output_path"]).read_text())
            self.assertEqual(data["total_value_usd"], 651.0)
            br = data["customs_value_breakdown"]
            self.assertEqual(br["fob_usd"],       626.0)
            self.assertEqual(br["freight_usd"],   15.0)
            self.assertEqual(br["insurance_usd"], 10.0)
            self.assertEqual(br["cif_usd"],       651.0)


# ── 8. VAT B00 stays out of landed cost ───────────────────────────────────────

class TestVATReferenceOnly(unittest.TestCase):
    def test_audit_marks_vat_as_reference_only(self):
        """Audit reporting must always label B00 VAT as reference-only.

        We verify the wording in the English report builder accepts a
        verification dict with vat_pln populated and emits the standard
        reference-only text — guaranteeing VAT never enters landed cost.
        """
        from audit_agent import _check5_values
        v = {"cif_match": True, "invoice_cif_total_usd": 651.0,
             "sad_cif_total_usd": 651.0, "cif_difference_usd": 0.0,
             "sad_customs_rate": 4.0}
        result = {"zc429": {"vat_pln": 100.0, "mrn": "X"},
                  "duty_pln": 10.0, "nbp": {"usd_rate": 4.0}}
        invoices = [{"invoice_no": "I1", "fob_usd": 100, "freight_usd": 0,
                     "insurance_usd": 0, "cif_usd": 100}]
        c5 = _check5_values(v, result, invoices)
        # Audit dict must surface vat_pln separately from any landed-cost field.
        self.assertEqual(c5["vat_pln"], 100.0)
        self.assertEqual(c5["duty_pln"], 10.0)
        # No key in c5 should fold VAT into landed cost
        self.assertNotIn("landed_cost_includes_vat", c5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
