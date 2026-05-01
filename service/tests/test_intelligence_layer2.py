"""
test_intelligence_layer2.py — Tests for Layer 1→2→3 integration modules.

New modules covered:
  - attachment_pattern_engine: detect_document_type()
  - sla_engine: check_sla(), compute_stage_durations(), get_sla_summary()
  - intelligence_engine: load_task_f_documents(), parse_all_documents(),
                         build_knowledge_base(), load_master()

Run:
    pytest service/tests/test_intelligence_layer2.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Attachment Pattern Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestAttachmentPatternEngine:

    def _classify(self, filename, mime=None):
        from app.services.attachment_pattern_engine import detect_document_type
        return detect_document_type(filename, mime)

    # ZC429 — most specific pattern
    def test_zc429_classified(self):
        r = self._classify("ZC429_26PL44302D005LJ4R0_1_PL.pdf")
        assert r["type"] == "zc429_sad"
        assert r["confidence"] == "high"
        assert r["mrn"] == "26PL44302D005LJ4R0"
        assert r["should_extract"] is True
        assert r["extract_target"] == "mrn"

    def test_zc429_case_insensitive(self):
        r = self._classify("zc429_ABCDEF123_1_PL.pdf")
        assert r["type"] == "zc429_sad"

    # DSK
    def test_dsk_classified(self):
        r = self._classify("DSK_20260115_001.pdf")
        assert r["type"] == "dsk"
        assert r["confidence"] == "high"

    # FedEx cesja
    def test_fedex_cesja_form_classified(self):
        r = self._classify("cesja_fedex_awb887467026597.pdf")
        assert r["type"] == "cesja_form_fedex"
        assert r["carrier"] == "FEDEX"
        assert r["alert"] is not None
        assert "pl-import@fedex.com" in r["alert"]

    def test_authorization_form_is_fedex_cesja(self):
        r = self._classify("authorization_form_estrella.pdf")
        assert r["type"] == "cesja_form_fedex"

    # DHL cesja
    def test_dhl_cesja_classified(self):
        r = self._classify("cesja_awb1234567890.pdf")
        assert r["type"] == "cesja_form_dhl"
        assert r["carrier"] == "DHL"
        assert r["should_extract"] is False  # ACS handles — no action for Estrella

    # PZC
    def test_pzc_classified(self):
        r = self._classify("PZC_2025_12_001.pdf")
        assert r["type"] == "pzc"

    def test_potwierdzenie_classified_as_pzc(self):
        r = self._classify("potwierdzenie_zgloszenia.pdf")
        assert r["type"] == "pzc"

    # ACS VAT statement
    def test_acs_vat_statement_classified(self):
        r = self._classify("vat_statement_2026_03.pdf")
        assert r["type"] == "acs_vat_statement"
        assert r["route_to"] == "accounting"

    # Ganther invoice
    def test_ganther_invoice_fv_prefix(self):
        r = self._classify("FV_20260115_001.pdf")
        assert r["type"] == "ganther_invoice"
        assert r["route_to"] == "accounting"

    def test_ganther_invoice_faktura_prefix(self):
        r = self._classify("faktura_VAT_ESTRELLA_2026.pdf")
        assert r["type"] == "ganther_invoice"

    # Commercial invoice
    def test_commercial_invoice_ejl(self):
        r = self._classify("EJL_2024_001_invoice.pdf")
        assert r["type"] == "commercial_invoice"
        assert r["route_to"] == "pz_processor"

    # Packing list
    def test_packing_list(self):
        r = self._classify("packing_list_EJL2024.pdf")
        assert r["type"] == "packing_list"

    # AWB label
    def test_awb_label(self):
        r = self._classify("awb_label_1234567890.pdf")
        assert r["type"] == "awb_label"

    # Unknown
    def test_unknown_pdf(self):
        r = self._classify("random_document.pdf", mime="application/pdf")
        assert r["type"] == "unknown"

    def test_unknown_no_extension(self):
        r = self._classify("no_extension_file")
        assert r["type"] == "unknown"

    # Return schema
    def test_result_has_required_keys(self):
        r = self._classify("ZC429_TEST123_1_PL.pdf")
        for key in ("type", "label", "carrier", "confidence", "mrn",
                    "should_extract", "extract_target", "route_to",
                    "alert", "contains"):
            assert key in r, f"Result missing key: {key}"

    # Batch classification
    def test_classify_attachments_batch(self):
        from app.services.attachment_pattern_engine import classify_attachments
        results = classify_attachments([
            "ZC429_26PL_1_PL.pdf",
            "DSK_001.pdf",
            "unknown.txt",
        ])
        assert len(results) == 3
        assert results[0]["type"] == "zc429_sad"
        assert results[1]["type"] == "dsk"
        assert results[2]["type"] == "unknown"

    # MRN extraction helper
    def test_extract_mrns_from_attachments(self):
        from app.services.attachment_pattern_engine import extract_mrns_from_attachments
        mrns = extract_mrns_from_attachments([
            "ZC429_MRNABC123_1_PL.pdf",
            "ZC429_MRNXYZ456_1_PL.pdf",
            "DSK_001.pdf",
        ])
        assert "MRNABC123" in mrns
        assert "MRNXYZ456" in mrns
        assert len(mrns) == 2

    def test_has_cesja_requiring_action(self):
        from app.services.attachment_pattern_engine import has_cesja_requiring_action
        assert has_cesja_requiring_action(["cesja_form.pdf"]) is True
        assert has_cesja_requiring_action(["DSK_001.pdf"]) is False

    def test_list_all_types(self):
        from app.services.attachment_pattern_engine import list_all_types
        types = list_all_types()
        assert isinstance(types, dict)
        assert len(types) >= 8
        assert "zc429_sad" in types
        assert "dsk" in types
        assert "unknown" in types


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SLA Engine
# ═══════════════════════════════════════════════════════════════════════════════

def _ts(hours_ago: float) -> str:
    """Generate ISO timestamp N hours ago."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def _event(name: str, hours_ago: float, detail: dict = None) -> dict:
    return {"event": name, "ts": _ts(hours_ago), "detail": detail or {}}


class TestSlaEngine:

    # ── Basic functionality ───────────────────────────────────────────────────

    def test_empty_timeline_returns_empty(self):
        from app.services.sla_engine import check_sla
        assert check_sla([], carrier="DHL") == []

    def test_no_violations_clean_timeline(self):
        from app.services.sla_engine import check_sla
        timeline = [
            _event("carrier_arrived",    100),
            _event("sad_uploaded",        98),
            _event("pzc_received",        90),
            _event("duty_note_received",  85),
            _event("payment_confirmed",   80),
            _event("clearance_started",   72),
        ]
        warnings = check_sla(timeline, carrier="DHL")
        # Clean timeline should have no violations (all well within SLA)
        assert all(w["severity"] != "HIGH" for w in warnings), (
            f"Unexpected HIGH violations: {[w['code'] for w in warnings if w['severity']=='HIGH']}"
        )

    # ── Duty payment SLA ──────────────────────────────────────────────────────

    def test_duty_payment_warning_at_80h(self):
        from app.services.sla_engine import check_sla
        timeline = [
            _event("duty_note_received", 80),  # 80h ago, no payment
        ]
        warnings = check_sla(timeline, carrier="DHL")
        codes = [w["code"] for w in warnings]
        assert "SLA_DUTY_TO_PAYMENT_PENDING" in codes

    def test_duty_payment_critical_at_200h(self):
        from app.services.sla_engine import check_sla
        timeline = [
            _event("duty_note_received", 200),  # 200h ago (>168h critical), no payment
        ]
        warnings = check_sla(timeline, carrier="DHL")
        codes = [w["code"] for w in warnings]
        high_codes = [w["code"] for w in warnings if w["severity"] == "HIGH"]
        assert any("DUTY" in c for c in high_codes), (
            f"Expected HIGH duty warning, got: {warnings}"
        )

    def test_duty_payment_resolved_no_warning(self):
        from app.services.sla_engine import check_sla
        timeline = [
            _event("duty_note_received", 80),
            _event("payment_confirmed",   60),  # paid 20h after notice
        ]
        warnings = check_sla(timeline, carrier="DHL")
        duty_warnings = [w for w in warnings if "DUTY" in w["code"]]
        # 20h between duty notice and payment — well within 72h warning threshold
        assert not any(w["severity"] == "HIGH" for w in duty_warnings)

    # ── Full clearance SLA ────────────────────────────────────────────────────

    def test_full_dhl_sla_breach(self):
        from app.services.sla_engine import check_sla
        timeline = [
            _event("carrier_arrived", 130),  # 130h ago = >120h DHL SLA, no clearance
        ]
        warnings = check_sla(timeline, carrier="DHL")
        codes = [w["code"] for w in warnings]
        assert "SLA_FULL_CLEARANCE_BREACH" in codes
        # Must be HIGH severity
        breach = next(w for w in warnings if w["code"] == "SLA_FULL_CLEARANCE_BREACH")
        assert breach["severity"] == "HIGH"

    def test_full_fedex_sla_longer_threshold(self):
        from app.services.sla_engine import check_sla
        # 130h is a breach for DHL (SLA=120h) but NOT for FedEx (SLA=216h)
        timeline = [_event("carrier_arrived", 130)]
        dhl_warnings   = check_sla(timeline, carrier="DHL")
        fedex_warnings = check_sla(timeline, carrier="FEDEX")

        dhl_breach   = any(w["code"] == "SLA_FULL_CLEARANCE_BREACH" for w in dhl_warnings)
        fedex_breach = any(w["code"] == "SLA_FULL_CLEARANCE_BREACH" for w in fedex_warnings)

        assert dhl_breach,    "DHL should breach at 130h"
        assert not fedex_breach, "FedEx should NOT breach at 130h (SLA=216h)"

    def test_at_risk_at_80pct_sla(self):
        from app.services.sla_engine import check_sla
        # 100h = 83% of 120h DHL SLA → should be at_risk (MEDIUM)
        timeline = [_event("carrier_arrived", 100)]
        warnings = check_sla(timeline, carrier="DHL")
        at_risk = any(w["code"] == "SLA_FULL_CLEARANCE_AT_RISK" for w in warnings)
        assert at_risk, f"Expected SLA_FULL_CLEARANCE_AT_RISK at 100h DHL, got: {[w['code'] for w in warnings]}"

    # ── FedEx cesja ──────────────────────────────────────────────────────────

    def test_fedex_cesja_delay_warning(self):
        from app.services.sla_engine import check_sla
        timeline = [
            _event("carrier_arrived", 30),  # 30h ago, no cesja submitted
        ]
        warnings = check_sla(timeline, carrier="FEDEX")
        codes = [w["code"] for w in warnings]
        assert "SLA_FEDEX_CESJA_DELAY_PENDING" in codes

    def test_fedex_cesja_resolved_no_warning(self):
        from app.services.sla_engine import check_sla
        timeline = [
            _event("carrier_arrived",  30),
            _event("cesja_submitted",  28),  # submitted 2h after arrival
        ]
        warnings = check_sla(timeline, carrier="FEDEX")
        cesja_warnings = [w for w in warnings if "CESJA" in w["code"]]
        assert not any(w["severity"] == "HIGH" for w in cesja_warnings)

    # ── Warning structure ────────────────────────────────────────────────────

    def test_warning_has_required_keys(self):
        from app.services.sla_engine import check_sla
        timeline = [_event("carrier_arrived", 130)]
        warnings = check_sla(timeline, carrier="DHL")
        assert len(warnings) > 0
        for w in warnings:
            for key in ("code", "severity", "message", "detail", "source"):
                assert key in w, f"Warning missing key: {key}"
            assert w["source"] == "sla_engine"

    def test_warnings_sorted_high_first(self):
        from app.services.sla_engine import check_sla
        timeline = [
            _event("carrier_arrived",   200),  # HIGH: full breach
            _event("duty_note_received", 80),   # MEDIUM: duty pending
        ]
        warnings = check_sla(timeline, carrier="DHL")
        if len(warnings) >= 2:
            severities = [w["severity"] for w in warnings]
            if "HIGH" in severities and "MEDIUM" in severities:
                assert severities.index("HIGH") < severities.index("MEDIUM")

    def test_awb_and_batch_in_detail(self):
        from app.services.sla_engine import check_sla
        timeline = [_event("carrier_arrived", 130)]
        warnings = check_sla(timeline, carrier="DHL", awb="1234567890", batch_id="BATCH_001")
        for w in warnings:
            assert w["detail"].get("awb") == "1234567890"
            assert w["detail"].get("batch_id") == "BATCH_001"

    # ── Stage durations ──────────────────────────────────────────────────────

    def test_compute_stage_durations(self):
        from app.services.sla_engine import compute_stage_durations
        timeline = [
            _event("carrier_arrived",    100),
            _event("sad_uploaded",        80),   # 20h after arrival
            _event("pzc_received",        60),   # 20h after SAD
            _event("duty_note_received",  40),   # 20h after PZC
            _event("payment_confirmed",   20),   # 20h after duty
        ]
        durations = compute_stage_durations(timeline)
        assert isinstance(durations, dict)
        # All DHL stages should have computed values
        for key in ("arrival_to_sad", "sad_to_pzc", "pzc_to_duty", "duty_to_payment"):
            val = durations.get(key)
            assert val is not None, f"Stage {key} should be computed"
            assert 15 < val < 25, f"Stage {key} should be ~20h, got {val}h"

    # ── SLA summary ──────────────────────────────────────────────────────────

    def test_get_sla_summary_structure(self):
        from app.services.sla_engine import get_sla_summary
        timeline = [
            _event("carrier_arrived", 60),
            _event("clearance_started", 10),
        ]
        summary = get_sla_summary(timeline, carrier="DHL")
        for key in ("carrier", "stage_durations_h", "violations", "at_risk",
                    "total_elapsed_h", "full_sla_h", "full_sla_pct"):
            assert key in summary, f"Summary missing key: {key}"
        assert summary["carrier"] == "DHL"
        assert summary["full_sla_h"] == 120
        assert summary["total_elapsed_h"] is not None
        assert summary["full_sla_pct"] is not None

    def test_get_sla_summary_fedex_sla(self):
        from app.services.sla_engine import get_sla_summary
        timeline = [_event("carrier_arrived", 50)]
        summary = get_sla_summary(timeline, carrier="FEDEX")
        assert summary["full_sla_h"] == 216

    # ── DHL-specific stages don't fire for FedEx ─────────────────────────────

    def test_dhl_stages_skip_for_fedex(self):
        from app.services.sla_engine import check_sla
        # DHL arrival without SAD — would fire SLA_ARRIVAL_TO_SAD for DHL
        timeline = [_event("carrier_arrived", 60)]
        dhl_warnings   = check_sla(timeline, carrier="DHL")
        fedex_warnings = check_sla(timeline, carrier="FEDEX")

        dhl_codes   = [w["code"] for w in dhl_warnings]
        fedex_codes = [w["code"] for w in fedex_warnings]

        # SAD stage is DHL-only — should not fire for FedEx
        assert not any("ARRIVAL_TO_SAD" in c for c in fedex_codes)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Intelligence Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntelligenceEngine:

    # ── Document loading ──────────────────────────────────────────────────────

    def test_load_task_f_documents_returns_tuple(self, tmp_path):
        from app.services.intelligence_engine import load_task_f_documents, TASK_F_DOCS
        # Patch to point to tmp_path where no docs exist
        with patch("app.services.intelligence_engine.TASK_F_DOCS",
                   [tmp_path / "fake.md"]), \
             patch("app.services.intelligence_engine.SUPPLEMENTARY_DOCS", []):
            content_map, parsed, missing = load_task_f_documents()
        assert isinstance(content_map, dict)
        assert isinstance(parsed, list)
        assert isinstance(missing, list)
        assert "fake.md" in missing

    def test_load_real_task_f_docs_if_available(self):
        """At least some Task F docs should exist and be loadable."""
        from app.services.intelligence_engine import load_task_f_documents
        content_map, parsed, missing = load_task_f_documents()
        # Should load at least some docs (Task F docs were written in this session)
        assert len(parsed) + len(missing) > 0
        # Any parsed doc should have non-empty content
        for name, content in content_map.items():
            assert len(content) > 100, f"Doc {name} too short"

    def test_load_docs_tolerates_all_missing(self, tmp_path):
        """Should not crash if all docs missing."""
        from app.services.intelligence_engine import load_task_f_documents
        with patch("app.services.intelligence_engine.TASK_F_DOCS", []),\
             patch("app.services.intelligence_engine.SUPPLEMENTARY_DOCS", []):
            content_map, parsed, missing = load_task_f_documents()
        assert content_map == {}
        assert parsed == []
        assert missing == []

    # ── Document parsing ──────────────────────────────────────────────────────

    def test_parse_all_documents_returns_dict(self):
        from app.services.intelligence_engine import parse_all_documents
        result = parse_all_documents(content_map={})  # empty content — should not crash
        assert isinstance(result, dict)
        for key in ("sla_benchmarks", "known_delay_incidents", "automation_opportunities",
                    "system_gaps", "actor_discoveries", "attachment_rules",
                    "carrier_rules", "risk_patterns", "awb_stats"):
            assert key in result, f"parse_all_documents missing key: {key}"

    def test_parse_with_automation_doc(self):
        """If AUTOMATION_OPPORTUNITY_MAP.md is available, extract opps."""
        from app.services.intelligence_engine import parse_all_documents, TASK_F_DOCS
        content_map, _, _ = __import__(
            "app.services.intelligence_engine",
            fromlist=["load_task_f_documents"],
        ).load_task_f_documents()

        result = parse_all_documents(content_map=content_map)
        opps = result["automation_opportunities"]
        # If the doc is present, should have extracted automation opportunities
        if any("AUTOMATION_OPPORTUNITY_MAP.md" in (k or "") for k in content_map):
            assert len(opps) > 0, "Expected automation opportunities from AUTOMATION_OPPORTUNITY_MAP.md"

    def test_parse_known_delays_hardcoded(self):
        """Known delay incidents are hardcoded from doc analysis — always present."""
        from app.services.intelligence_engine import parse_all_documents
        result = parse_all_documents(content_map={})
        delays = result["known_delay_incidents"]
        assert len(delays) == 2
        awbs = [d["awb"] for d in delays]
        assert "6883058851" in awbs  # VAT deferment — Dec 2025
        assert "2824221912" in awbs  # Duty routing gap — Mar 2026

    def test_parse_risk_patterns_hardcoded(self):
        from app.services.intelligence_engine import parse_all_documents
        result = parse_all_documents(content_map={})
        risks = result["risk_patterns"]
        codes = [r["code"] for r in risks]
        assert "DUTY_ROUTING_GAP" in codes
        assert "VAT_DEFERMENT_GAP" in codes
        assert "FEDEX_CESJA_NOT_SUBMITTED" in codes

    def test_parse_carrier_rules(self):
        from app.services.intelligence_engine import parse_all_documents
        result = parse_all_documents(content_map={})
        cr = result["carrier_rules"]
        assert "DHL" in cr
        assert "FEDEX" in cr
        assert cr["DHL"]["sla_hours"] == 120
        assert cr["FEDEX"]["sla_hours"] == 216
        assert cr["FEDEX"]["cesja_type"] == "manual"

    def test_parse_awb_patterns(self):
        from app.services.intelligence_engine import parse_all_documents
        import re
        result = parse_all_documents(content_map={})
        patterns = result["awb_patterns"]
        # DHL pattern should match 10-digit AWB
        assert re.search(patterns["DHL"], "1234567890")
        # FedEx pattern should match 12-digit AWB
        assert re.search(patterns["FEDEX"], "123456789012")

    def test_parse_sla_benchmarks(self):
        from app.services.intelligence_engine import parse_all_documents
        result = parse_all_documents(content_map={})
        sla = result["sla_benchmarks"]
        assert sla["DHL"]["total_hours"] == 120
        assert sla["FEDEX"]["total_hours"] == 216
        assert "thresholds" in sla
        assert sla["thresholds"]["duty_payment_warning_h"] == 72

    def test_actor_discoveries_are_new_emails(self):
        """actor_discoveries should only contain emails not in known actor list."""
        from app.services.intelligence_engine import parse_all_documents
        from app.services.intelligence_parser import _ACTORS
        known = {a.email.lower() for a in _ACTORS}

        content_map = {
            "fake_doc.md": "Hello from newperson@newdomain.com and also admin@unknown-customs.pl",
        }
        result = parse_all_documents(content_map=content_map)
        discovered = {d["email"] for d in result["actor_discoveries"]}
        # None of the discovered emails should be in known list
        overlap = discovered & known
        assert not overlap, f"Discovered actors overlap with known: {overlap}"

    def test_actor_discoveries_skips_placeholder_domains(self):
        from app.services.intelligence_engine import parse_all_documents
        content_map = {
            "fake.md": "example@example.com and test@test.com should be skipped",
        }
        result = parse_all_documents(content_map=content_map)
        emails = {d["email"] for d in result["actor_discoveries"]}
        assert "example@example.com" not in emails
        assert "test@test.com" not in emails

    # ── Build pipeline ────────────────────────────────────────────────────────

    def test_build_knowledge_base_creates_file(self, tmp_path):
        from app.services.intelligence_engine import build_knowledge_base
        output = tmp_path / "test_master.json"
        saved = build_knowledge_base(output_path=output)
        assert saved.exists()
        raw = json.loads(saved.read_text(encoding="utf-8"))
        assert raw["version"] is not None
        assert "generated_at" in raw
        assert "known_delay_incidents" in raw
        assert "automation_opportunities" in raw

    def test_build_creates_storage_dir_if_missing(self, tmp_path):
        from app.services.intelligence_engine import build_knowledge_base
        nested = tmp_path / "deep" / "nested" / "master.json"
        build_knowledge_base(output_path=nested)
        assert nested.exists()

    def test_build_atomic_write(self, tmp_path):
        """After build, no .tmp file should remain."""
        from app.services.intelligence_engine import build_knowledge_base
        output = tmp_path / "master.json"
        build_knowledge_base(output_path=output)
        tmp = output.with_suffix(".json.tmp")
        assert not tmp.exists(), ".tmp file should be cleaned up after atomic write"

    def test_build_json_is_valid(self, tmp_path):
        from app.services.intelligence_engine import build_knowledge_base
        output = tmp_path / "master.json"
        build_knowledge_base(output_path=output)
        # Should parse without error
        data = json.loads(output.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    # ── Loader ────────────────────────────────────────────────────────────────

    def test_load_master_returns_none_if_missing(self, tmp_path):
        from app.services.intelligence_engine import load_master, MASTER_PATH
        with patch("app.services.intelligence_engine.MASTER_PATH", tmp_path / "nonexistent.json"):
            result = load_master(force_reload=True)
        assert result is None

    def test_load_master_returns_dict_if_present(self, tmp_path):
        from app.services.intelligence_engine import build_knowledge_base, load_master, MASTER_PATH
        output = tmp_path / "master.json"
        build_knowledge_base(output_path=output)
        with patch("app.services.intelligence_engine.MASTER_PATH", output):
            result = load_master(force_reload=True)
        assert result is not None
        assert isinstance(result, dict)
        assert result["version"] is not None

    # ── SLA threshold helper ──────────────────────────────────────────────────

    def test_get_sla_thresholds_fallback(self, tmp_path):
        """Should return defaults when master not available."""
        from app.services.intelligence_engine import get_sla_thresholds_from_master, MASTER_PATH
        with patch("app.services.intelligence_engine.MASTER_PATH", tmp_path / "nonexistent.json"):
            # Reset cache
            import app.services.intelligence_engine as ie
            ie._master_cache = None
            thresholds = get_sla_thresholds_from_master()
        assert thresholds["duty_payment_warning_h"] == 72
        assert thresholds["duty_payment_critical_h"] == 168

    def test_get_automation_opportunities_filtered_by_phase(self, tmp_path):
        from app.services.intelligence_engine import (
            build_knowledge_base, load_master, get_automation_opportunities, MASTER_PATH
        )
        output = tmp_path / "master.json"
        build_knowledge_base(output_path=output)
        with patch("app.services.intelligence_engine.MASTER_PATH", output):
            import app.services.intelligence_engine as ie
            ie._master_cache = None
            _ = load_master(force_reload=True)
            p1_opps = get_automation_opportunities(phase="P1")

        # All returned opps should be phase P1
        for op in p1_opps:
            assert op.get("phase") == "P1", f"Expected P1, got: {op.get('phase')}"

    def test_get_automation_opportunities_empty_when_no_master(self, tmp_path):
        from app.services.intelligence_engine import get_automation_opportunities, MASTER_PATH
        with patch("app.services.intelligence_engine.MASTER_PATH", tmp_path / "nonexistent.json"):
            import app.services.intelligence_engine as ie
            ie._master_cache = None
            opps = get_automation_opportunities()
        assert opps == []


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Cross-module integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossModuleIntegration:
    """Verify that the new modules work together correctly."""

    def test_attachment_engine_mrns_feed_timeline(self):
        """MRN extracted by attachment_engine can be used in a timeline event."""
        from app.services.attachment_pattern_engine import extract_mrns_from_attachments
        from app.services.sla_engine import _event, check_sla

        filenames = ["ZC429_26PL44302D005LJ4R0_1_PL.pdf"]
        mrns = extract_mrns_from_attachments(filenames)
        assert len(mrns) == 1

        # Can create a timeline event from extracted MRN
        timeline = [
            {"event": "carrier_arrived", "ts": _ts(50), "detail": {}},
            {"event": "sad_uploaded",    "ts": _ts(45), "detail": {"mrn": mrns[0]}},
        ]
        # Should not produce SAD-related SLA violations
        warnings = check_sla(timeline, carrier="DHL")
        sad_violations = [w for w in warnings if "ARRIVAL_TO_SAD" in w["code"]
                          and w["severity"] == "HIGH"]
        assert not sad_violations

    def test_intelligence_engine_risk_patterns_match_risk_detector_codes(self):
        """Risk pattern codes from master should match codes in risk_detector."""
        from app.services.intelligence_engine import parse_all_documents
        from app.services.risk_detector import (
            detect_duty_routing_gap, detect_vat_deferment,
            detect_fca_complication, detect_unknown_sender,
        )

        master_risks = parse_all_documents(content_map={})["risk_patterns"]
        master_codes = {r["code"] for r in master_risks}

        # At least some codes should match detectable risks
        detected_codes = set()

        # Test each detector
        detected_codes.update(w["code"] for w in detect_duty_routing_gap("amit@estrellajewels.eu"))
        detected_codes.update(w["code"] for w in detect_vat_deferment("brak pozwolenia na odroczenie VAT"))
        detected_codes.update(w["code"] for w in detect_fca_complication("FCA transport invoice"))
        detected_codes.update(w["code"] for w in detect_unknown_sender("random@unknown.com"))

        overlap = master_codes & detected_codes
        assert len(overlap) >= 2, (
            f"Expected ≥2 matching codes between master and detectors. "
            f"Master: {master_codes}, Detected: {detected_codes}, Overlap: {overlap}"
        )

    def test_sla_engine_thresholds_consistent_with_intelligence_engine(self):
        """SLA engine critical thresholds should be consistent with intelligence engine."""
        from app.services.sla_engine import _FULL_SLA_DHL_H, _FULL_SLA_FEDEX_H
        from app.services.intelligence_engine import parse_all_documents

        benchmarks = parse_all_documents(content_map={})["sla_benchmarks"]
        assert _FULL_SLA_DHL_H   == benchmarks["DHL"]["total_hours"]
        assert _FULL_SLA_FEDEX_H == benchmarks["FEDEX"]["total_hours"]
